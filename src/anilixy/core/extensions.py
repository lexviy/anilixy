"""Extensions: where manga chapters and light novel volumes come from.

anilixy is a reader: it doesn't know any site. Sources come from extensions, which
are Python files the user puts in EXTENSIONS_DIR (or the folder named by the
ANILIXY_EXTENSIONS environment variable). Each is a ``.py`` file, or a folder with
an ``__init__.py``, that sets::

    API = 1

and defines any of::

    def manga(): return [...]    # manga sources
    def novels(): return [...]   # light novel sources

A manga source is any object with:

    id             short and stable: it is saved with progress and synced with
                   aniliphy, so it must never change
    name           shown to the user
    image_headers  (optional) a dict of headers for downloading page images
    search(query)            -> [{"title": str, "url": str}, ...]
    get_chapters(series_url) -> [{"name": str, "link": str}, ...], oldest first
    get_pages(chapter_link)  -> [{"index": int, "url": str}, ...]

A light novel source is any object with ``id``, ``name`` and:

    find_work(title) -> (page_url or None, [{"title": str, "url": str}, ...])

Extensions may use requests and BeautifulSoup (bs4), which anilixy already brings.
"""

import importlib.util
import logging
import os
import sys
import threading
import types
from dataclasses import dataclass, field
from pathlib import Path

from anilixy.core.storage import DATA_DIR

log = logging.getLogger(__name__)

API_VERSION = 1
MODULE_PREFIX = "anilixy_extensions"

MANGA_METHODS = ("search", "get_chapters", "get_pages")
NOVEL_METHODS = ("find_work",)


@dataclass
class InstalledExtension:
    name: str
    path: Path
    problem: str | None = None
    sources: list[str] = field(default_factory=list)


@dataclass
class _Loaded:
    installed: list[InstalledExtension]
    manga: list
    novels: list


_lock = threading.Lock()
_loaded: _Loaded | None = None
_for_tests: list | None = None


def extensions_dir() -> Path:
    custom = os.environ.get("ANILIXY_EXTENSIONS")
    return Path(custom).expanduser() if custom else DATA_DIR / "extensions"


def installed() -> list[InstalledExtension]:
    return _get().installed


def manga_sources() -> list:
    return _get().manga


def novel_sources() -> list:
    return _get().novels


def reload() -> None:
    global _loaded
    with _lock:
        _loaded = None


def use_for_tests(*modules) -> None:
    """Loads these objects (anything with API, manga() and novels()) instead of the folder."""
    global _for_tests
    _for_tests = list(modules) if modules else None
    reload()


def _get() -> _Loaded:
    global _loaded
    with _lock:
        if _loaded is None:
            _loaded = _load()
        return _loaded


def _candidates(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    found = []
    for path in sorted(folder.iterdir(), key=lambda p: p.name.lower()):
        if path.name.startswith((".", "_")):
            continue
        if path.is_file() and path.suffix == ".py" or path.is_dir() and (path / "__init__.py").is_file():
            found.append(path)
    return found


def _import(path: Path):
    if MODULE_PREFIX not in sys.modules:
        parent = types.ModuleType(MODULE_PREFIX)
        parent.__path__ = []
        sys.modules[MODULE_PREFIX] = parent
    name = f"{MODULE_PREFIX}.{path.stem if path.is_file() else path.name}"
    # Forget what an earlier load imported, so a reload picks up changed files.
    for loaded in [m for m in sys.modules if m == name or m.startswith(name + ".")]:
        del sys.modules[loaded]
    if path.is_dir():
        spec = importlib.util.spec_from_file_location(
            name, path / "__init__.py", submodule_search_locations=[str(path)]
        )
    else:
        spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"can't read {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


def _valid(source, methods) -> bool:
    if not isinstance(getattr(source, "id", None), str) or not source.id:
        return False
    if not isinstance(getattr(source, "name", None), str):
        return False
    return all(callable(getattr(source, method, None)) for method in methods)


def _sources(module, kind, methods, problems) -> list:
    make = getattr(module, kind, None)
    if make is None:
        return []
    try:
        sources = list(make() or [])
    except Exception as error:
        log.warning("Extension %s failed to list its %s sources", module, kind, exc_info=True)
        problems.append(f"Its {kind} sources failed: {type(error).__name__}")
        return []
    good = [source for source in sources if _valid(source, methods)]
    if len(good) < len(sources):
        problems.append(f"{len(sources) - len(good)} {kind} source(s) are missing an id, a name or a method")
    return good


def _check_api(module) -> str | None:
    api = getattr(module, "API", None)
    if not isinstance(api, int) or api < 1:
        return "It doesn't say which version of anilixy it was made for (API = 1)"
    if api > API_VERSION:
        return "It needs a newer anilixy"
    return None


def _one(name, path, module, manga, novels) -> InstalledExtension:
    found = InstalledExtension(name=name, path=path)
    found.problem = _check_api(module)
    if found.problem:
        return found
    problems = []
    for kind, methods, into in (("manga", MANGA_METHODS, manga), ("novels", NOVEL_METHODS, novels)):
        for source in _sources(module, kind, methods, problems):
            found.sources.append(source.name)
            into.append(source)
    if problems:
        found.problem = "; ".join(problems)
    return found


def _load() -> _Loaded:
    manga, novels, extensions = [], [], []
    if _for_tests is not None:
        for module in _for_tests:
            name = getattr(module, "__name__", type(module).__name__)
            extensions.append(_one(name, Path(name), module, manga, novels))
    else:
        for path in _candidates(extensions_dir()):
            name = path.stem if path.is_file() else path.name
            try:
                module = _import(path)
            except Exception as error:
                log.warning("Could not load the extension %s", path, exc_info=True)
                extensions.append(
                    InstalledExtension(name, path, f"It failed to load: {type(error).__name__} ({error})")
                )
                continue
            extensions.append(_one(name, path, module, manga, novels))
    return _Loaded(extensions, _first_of_each(manga), _first_of_each(novels))


def _first_of_each(sources) -> list:
    """Two extensions may bring a source with the same id: the first one wins."""
    seen = set()
    kept = []
    for source in sources:
        if source.id not in seen:
            seen.add(source.id)
            kept.append(source)
    return kept


def find_manga(source_id: str):
    return next((source for source in manga_sources() if source.id == source_id), None)


def find_novels(source_id: str):
    return next((source for source in novel_sources() if source.id == source_id), None)
