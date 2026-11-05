from anilixy.core.storage import CONFIG_DIR, load_json, write_json

SEEN_FILE = CONFIG_DIR / "seen_episodes.json"


def _load() -> dict:
    return load_json(SEEN_FILE)


def _save(data: dict) -> None:
    write_json(SEEN_FILE, data)


def check_new(entries) -> dict:
    data = _load()
    changed = False
    new = {}
    for entry in entries:
        media = entry["media"]
        airing = media.get("nextAiringEpisode")
        if not airing:
            continue
        released = airing["episode"] - 1
        if released < 1:
            continue
        key = str(media["id"])
        seen = data.get(key)
        progress = entry.get("progress") or 0
        if seen is None:
            data[key] = released
            changed = True
        elif released > seen:
            if released > progress:
                new[key] = released
            else:
                data[key] = released
                changed = True
    if changed:
        _save(data)
    return new


def mark_seen(media_id, episode) -> None:
    data = _load()
    if data.get(str(media_id)) != episode:
        data[str(media_id)] = episode
        _save(data)
