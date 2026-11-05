from dataclasses import dataclass, field


@dataclass(frozen=True)
class MangaSource:
    prefix: str
    name: str
    module: str
    attr: str
    image_headers: dict = field(default_factory=dict)

    @property
    def client(self):
        from importlib import import_module

        return getattr(import_module(self.module), self.attr)


MANGA_SOURCES = (
    MangaSource("weeb", "WeebCentral", "anilixy.manga.sources.weebcentral", "weebcentral"),
    MangaSource(
        "town",
        "MangaTown",
        "anilixy.manga.sources.mangatown",
        "mangatown",
        {"Referer": "https://www.mangatown.com/"},
    ),
)

_BY_PREFIX = {source.prefix: source for source in MANGA_SOURCES}


def source_for(source_id) -> MangaSource | None:
    prefix, sep, _ = str(source_id or "").partition(":")
    return _BY_PREFIX.get(prefix) if sep else None


def source_by_prefix(prefix) -> MangaSource | None:
    return _BY_PREFIX.get(prefix)


def split_source_id(source_id):
    source = source_for(source_id)
    if source is None:
        return None, None
    return source, str(source_id).partition(":")[2]


def make_source_id(source: MangaSource, series_url: str) -> str:
    return f"{source.prefix}:{series_url}"
