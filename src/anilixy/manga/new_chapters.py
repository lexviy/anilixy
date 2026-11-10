import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from anilixy.core.storage import CONFIG_DIR, load_json, write_json
from anilixy.manga.history import get_mapping
from anilixy.manga.sources import split_source_id

log = logging.getLogger(__name__)

SEEN_FILE = CONFIG_DIR / "seen_chapters.json"
MAX_AGE = 30 * 60
_lock = threading.Lock()


def _load() -> dict:
    return load_json(SEEN_FILE)


def _save(data: dict) -> None:
    write_json(SEEN_FILE, data, indent=2)


def chapter_number(name) -> float | None:
    numbers = re.findall(r"\d+(?:\.\d+)?", str(name or ""))
    return float(numbers[-1]) if numbers else None


def latest_chapter(source_id) -> float | None:
    source, series_url = split_source_id(source_id)
    if source is None:
        return None
    chapters = source.get_chapters(series_url)
    numbers = [n for n in (chapter_number(c.get("name")) for c in chapters) if n is not None]
    return max(numbers) if numbers else None


def _trackable(entry) -> bool:
    media = entry.get("media") or {}
    return media.get("format") != "NOVEL" and entry.get("status") in ("CURRENT", "REPEATING", None)


def cached_unread(entries) -> dict:
    data = _load()
    unread = {}
    for entry in entries:
        key = str(entry["media"]["id"])
        latest = (data.get(key) or {}).get("latest")
        if latest is not None and latest > (entry.get("progress") or 0) and _trackable(entry):
            unread[key] = latest
    return unread


def check(entries, max_age=MAX_AGE, workers=3) -> dict:
    data = _load()
    now = time.time()
    todo = []
    for entry in entries:
        if not _trackable(entry):
            continue
        key = str(entry["media"]["id"])
        source_id = get_mapping(key)
        if split_source_id(source_id)[0] is None:
            continue
        saved = data.get(key) or {}
        if saved.get("source_id") == source_id and now - saved.get("checked", 0) < max_age:
            continue
        todo.append((key, source_id))

    def lookup(item):
        key, source_id = item
        try:
            return key, source_id, latest_chapter(source_id)
        except Exception:
            log.warning("Could not check new chapters for %s", source_id, exc_info=True)
            return key, source_id, None

    fresh = {}
    if todo:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(lookup, todo))
        progress = {str(e["media"]["id"]): e.get("progress") or 0 for e in entries}
        with _lock:
            data = _load()
            for key, source_id, latest in results:
                if latest is None:
                    continue
                saved = data.get(key) or {}
                previous = saved.get("latest") if saved.get("source_id") == source_id else None
                if previous is not None and latest > previous and latest > progress.get(key, 0):
                    fresh[key] = latest
                data[key] = {"source_id": source_id, "latest": latest, "checked": now}
            _save(data)
    return {"unread": cached_unread(entries), "fresh": fresh}
