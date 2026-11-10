import time

from anilixy.core.storage import CONFIG_DIR, load_json, write_json

RESUME_FILE = CONFIG_DIR / "resume.json"


def _load() -> dict:
    return load_json(RESUME_FILE)


def _save(data: dict) -> None:
    write_json(RESUME_FILE, data)


def load_resumes() -> dict:
    return _load()


def load_resume(media_id):
    return _load().get(str(media_id))


def save_resume(anime, episode, position, duration=None) -> None:
    data = _load()
    data[str(anime["id"])] = {
        "episode": episode,
        "position": round(position, 1),
        "duration": round(duration, 1) if duration else None,
        "title": anime["title"],
        "episodes": anime["episodes"],
        "updated": time.time(),
    }
    _save(data)


def clear_resume(media_id) -> None:
    data = _load()
    if str(media_id) in data:
        del data[str(media_id)]
        _save(data)


def format_time(seconds) -> str:
    seconds = int(seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"
