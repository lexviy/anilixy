"""Manga sources, as brought by extensions (see anilixy.core.extensions).

A saved series is "<source id>:<series url>". The id stays saved even when its
extension is removed, so saved chapters can still be read.
"""

from anilixy.core import extensions


def manga_sources() -> list:
    return extensions.manga_sources()


def parse_source_id(source_id) -> tuple[str, str] | None:
    """Splits a saved series into (source id, series url), whether its source is installed or not."""
    prefix, sep, rest = str(source_id or "").partition(":")
    if not sep or not prefix or not rest:
        return None
    return prefix, rest


def source_for(source_id):
    parsed = parse_source_id(source_id)
    return extensions.find_manga(parsed[0]) if parsed else None


def source_by_prefix(prefix):
    return extensions.find_manga(prefix)


def split_source_id(source_id):
    source = source_for(source_id)
    if source is None:
        return None, None
    return source, str(source_id).partition(":")[2]


def make_source_id(source, series_url: str) -> str:
    return f"{source.id}:{series_url}"


def image_headers(source) -> dict:
    return dict(getattr(source, "image_headers", None) or {})


def source_label(source_id) -> str | None:
    """The name of the saved source, or its id when its extension isn't installed."""
    source = source_for(source_id)
    if source is not None:
        return source.name
    parsed = parse_source_id(source_id)
    return f"{parsed[0]} (not installed)" if parsed else None


def missing_source(source_id) -> str | None:
    """The id of the saved source when its extension isn't installed."""
    parsed = parse_source_id(source_id)
    return parsed[0] if parsed and source_for(source_id) is None else None


def openable(anilist_id, source_id) -> bool:
    """The saved series can be opened: its source is installed, or it has chapters saved offline."""
    if source_for(source_id) is not None:
        return True
    if parse_source_id(source_id) is None:
        return False
    from anilixy.manga import offline

    return bool(offline.cached_chapters(anilist_id, source_id))


def not_installed_message(source_id) -> str:
    return (
        f'The "{source_id}" source isn\'t installed. Install its extension '
        "(Settings → Extensions), or pick another one with Source."
    )


NO_SOURCES = "No manga source is installed. Add one in Settings → Extensions."
