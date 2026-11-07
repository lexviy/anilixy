import logging
import time

from anilixy.core.storage import CONFIG_DIR, load_json, write_json

log = logging.getLogger(__name__)


MANGA_MAP_PATH = CONFIG_DIR / "manga_map.json"
MANGA_HISTORY_PATH = CONFIG_DIR / "manga_history.json"


def _ensure():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def load_map():
    return load_json(MANGA_MAP_PATH)


def save_map(manga_map):
    _ensure()
    try:
        write_json(MANGA_MAP_PATH, manga_map, indent=2)
    except Exception:
        log.debug("ignored error", exc_info=True)


def load_history():
    return load_json(MANGA_HISTORY_PATH)


def save_history(history):
    _ensure()
    try:
        write_json(MANGA_HISTORY_PATH, history, indent=2)
    except Exception:
        log.debug("ignored error", exc_info=True)


def get_mapping(anilist_id):
    m = load_map()
    return m.get(str(anilist_id)) or m.get(anilist_id)


def set_mapping(anilist_id, source_id):
    m = load_map()
    m[str(anilist_id)] = source_id
    save_map(m)


def forget_mapping(anilist_id) -> bool:
    m = load_map()
    removed = m.pop(str(anilist_id), None) is not None
    if removed:
        save_map(m)
    return removed


def get_last_chapter(anilist_id):
    h = load_history()
    return h.get(str(anilist_id)) or h.get(anilist_id)


def clear_last_chapter(anilist_id):
    h = load_history()
    removed = h.pop(str(anilist_id), None) is not None
    removed = h.pop(anilist_id, None) is not None or removed
    if removed:
        save_history(h)


def set_last_chapter(anilist_id, chapter_id, chapter_number=None, page=0, title=None):
    h = load_history()
    h[str(anilist_id)] = {
        "chapter_id": chapter_id,
        "chapter_number": chapter_number,
        "page": page,
        "title": title,
        "updated": time.time(),
    }
    save_history(h)


def local_manga() -> list:
    items = [
        (key, item)
        for key, item in load_history().items()
        if isinstance(item, dict) and item.get("title") and key.isdigit()
    ]
    return [
        {
            "progress": item.get("chapter_number"),
            "updated": item.get("updated", 0),
            "media": {
                "id": int(key),
                "title": {"english": item["title"], "romaji": item["title"]},
                "chapters": None,
            },
        }
        for key, item in items
    ]


def set_last_page(anilist_id, chapter_id, page):
    h = load_history()
    item = h.get(str(anilist_id))
    if (
        isinstance(item, dict)
        and item.get("chapter_id") == chapter_id
        and item.get("page") != page
    ):
        item["page"] = page
        save_history(h)
