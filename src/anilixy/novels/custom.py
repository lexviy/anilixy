import re
from pathlib import Path

from anilixy.core.storage import CONFIG_DIR, load_json, write_json
from anilixy.novels import jnovels
from anilixy.novels.reading import forget_novel, last_read

CUSTOM_FILE = CONFIG_DIR / "custom_novels.json"
PREFIX = "custom:"

VOLUME_SUFFIX = re.compile(
    r"[\s_\-–:(\[]*(?:vol(?:ume)?\.?|v)\s*\d+.*$", re.IGNORECASE
)


def _load() -> dict:
    return load_json(CUSTOM_FILE)


def _save(data: dict) -> None:
    write_json(CUSTOM_FILE, data, ensure_ascii=False)


def _slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "novel"


def _entry(key, item) -> dict:
    return {
        "id": str(key),
        "title": item.get("title") or str(key),
        "files": item.get("files") or None,
    }


def list_entries() -> list[dict]:
    entries = [
        _entry(key, item) for key, item in _load().items() if isinstance(item, dict)
    ]
    entries.sort(key=lambda e: e["title"].lower())
    return entries


def get(key) -> dict | None:
    item = _load().get(str(key))
    return _entry(key, item) if isinstance(item, dict) else None


def guess_title(path) -> str:
    stem = Path(path).stem
    return VOLUME_SUFFIX.sub("", stem).strip(" -_") or stem


def add(title: str, files=None) -> tuple[str, bool]:
    title = title.strip()
    key = PREFIX + _slug(title)
    data = _load()
    if key in data:
        return key, False
    data[key] = {"title": title}
    if files:
        data[key]["files"] = [str(f) for f in files]
    _save(data)
    return key, True


def update(key, title: str, files=None) -> bool:
    data = _load()
    item = data.get(str(key))
    if not isinstance(item, dict):
        return False
    item["title"] = title.strip() or item.get("title") or str(key)
    if files:
        item["files"] = [str(f) for f in files]
    else:
        item.pop("files", None)
    _save(data)
    return True


def volumes(entry) -> list[Path]:
    files = entry.get("files")
    if files:
        found = [Path(f) for f in files if Path(f).is_file()]
        return sorted(found, key=jnovels.natural_key)
    return jnovels.get_local_volumes(entry["title"])


def remove(key) -> None:
    data = _load()
    if data.pop(str(key), None) is not None:
        _save(data)
    forget_novel(key)


def progress_label(key) -> str:
    last = last_read(key)
    if not last:
        return "custom"
    name, chapter = last
    return f"custom · {Path(name).stem} · ch {chapter}"
