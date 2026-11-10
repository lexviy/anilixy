from anilixy.core.storage import CONFIG_DIR, load_json, write_json

ENTRIES_FILE = CONFIG_DIR / "entries.json"


def _load() -> dict:
    return load_json(ENTRIES_FILE)


def _save(data: dict) -> None:
    write_json(ENTRIES_FILE, data)


def load_entry(media_id):
    return _load().get(str(media_id))


def save_entry(media_id, entry) -> None:
    data = _load()
    data[str(media_id)] = entry
    _save(data)


def forget_entry(media_id) -> None:
    data = _load()
    if str(media_id) in data:
        del data[str(media_id)]
        _save(data)
