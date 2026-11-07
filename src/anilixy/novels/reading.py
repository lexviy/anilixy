import time
from pathlib import Path

from anilixy.core.storage import CONFIG_DIR, load_json, write_json

NOVEL_PROGRESS_FILE = CONFIG_DIR / "novel_progress.json"
LEGACY_BOOK = "_legacy"


def _load() -> dict:
    return load_json(NOVEL_PROGRESS_FILE)


def _save(data: dict) -> None:
    write_json(NOVEL_PROGRESS_FILE, data)


def _media(data: dict, media_id) -> dict:
    item = data.get(str(media_id))
    if isinstance(item, dict) and "books" in item:
        return item
    if isinstance(item, dict):
        return {"last": LEGACY_BOOK, "books": {LEGACY_BOOK: item}}
    if isinstance(item, int):
        return {
            "last": LEGACY_BOOK,
            "books": {LEGACY_BOOK: {"chapter": item, "start_set": True, "start": 0}},
        }
    return {"last": None, "books": {}}


def _upgrade(book: dict) -> dict:
    if "segments" in book:
        return book
    segments = []
    if book.get("start_set"):
        segments = [[book.get("start", 0), book.get("end")]]
    return {"chapter": book.get("chapter", 0), "segments": segments, "length": 0}


def _book(media: dict, book_key: str) -> dict:
    books = media["books"]
    if book_key not in books and LEGACY_BOOK in books:
        books[book_key] = books.pop(LEGACY_BOOK)
    book = _upgrade(books.get(book_key, {}))
    books[book_key] = book
    return book


def counted(segments, length, upto=None) -> int:
    last = length - 1
    total = 0
    for start, end in segments:
        stop = last if end is None else end
        if upto is not None:
            stop = min(stop, upto)
        total += max(0, stop - start + 1)
    return total


def get_novel_state(media_id, book_key) -> dict:
    media = _media(_load(), media_id)
    book = _book(media, book_key)
    return {**book, "segments": [list(s) for s in book["segments"]]}


def save_novel_state(media_id, book_key, *, touch=True, title=None, **fields) -> None:
    data = _load()
    media = _media(data, media_id)
    _book(media, book_key).update(fields)
    if touch:
        media["last"] = book_key
        media["updated"] = time.time()
    if title:
        media["title"] = title
    data[str(media_id)] = media
    _save(data)


def base_for(media_id, volumes, volume_index) -> int:
    data = _load()
    media = _media(data, media_id)
    total = 0
    for path in volumes[:volume_index]:
        book = _book(media, Path(path).name)
        total += counted(book["segments"], book["length"])
    return total


def pick_volume(volumes, media_id) -> int:
    last = _media(_load(), media_id).get("last")
    for i, path in enumerate(volumes):
        if Path(path).name == last:
            return i
    return 0


def reset_novel_progress(media_id) -> None:
    data = _load()
    if str(media_id) not in data:
        return
    media = _media(data, media_id)
    for key in list(media["books"]):
        book = _book(media, key)
        book["chapter"] = 0
        book["position"] = 0.0
        book["segments"] = []
    media["last"] = None
    data[str(media_id)] = media
    _save(data)


def last_read(media_id):
    media = _media(_load(), media_id)
    last = media.get("last")
    book = media["books"].get(last) if last else None
    if not book:
        return None
    book = _upgrade(book)
    return last, book.get("chapter", 0) + 1


def local_novels() -> list:
    entries = []
    for key, item in _load().items():
        if not (isinstance(item, dict) and item.get("title") and item.get("last")):
            continue
        last = last_read(key)
        if last is None:
            continue
        entries.append(
            {
                "progress": last[1],
                "updated": item.get("updated", 0),
                "media": {
                    "id": int(key),
                    "title": {"english": item["title"], "romaji": item["title"]},
                    "chapters": None,
                    "format": "NOVEL",
                },
            }
        )
    return entries


def forget_novel(media_id) -> None:
    data = _load()
    if data.pop(str(media_id), None) is not None:
        _save(data)
