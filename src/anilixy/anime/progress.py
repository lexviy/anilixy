import time

from anilixy.core.storage import CONFIG_DIR, load_json, write_json

PROGRESS_FILE = CONFIG_DIR / "progress.json"


def _load() -> dict:
    return load_json(PROGRESS_FILE)


def _save(data: dict) -> None:
    write_json(PROGRESS_FILE, data)


def get_local_progress(media_id) -> int:
    return _load().get(str(media_id), {}).get("progress", 0)


def save_local_progress(anime, episode) -> bool:
    data = _load()
    key = str(anime["id"])

    if episode <= data.get(key, {}).get("progress", 0):
        return False

    data[key] = {
        "progress": episode,
        "title": anime["title"],
        "episodes": anime["episodes"],
        "updated": time.time(),
    }
    _save(data)
    return True


def local_entries() -> list:
    entries = []
    for key, item in sorted(
        _load().items(), key=lambda kv: kv[1].get("updated", 0), reverse=True
    ):
        total = item.get("episodes")
        if total and item["progress"] >= total:
            continue
        entries.append(
            {
                "progress": item["progress"],
                "media": {
                    "id": int(key),
                    "title": item["title"],
                    "episodes": total,
                    "nextAiringEpisode": None,
                },
            }
        )
    return entries
