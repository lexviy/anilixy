import hashlib
import logging
import re
import shutil
import threading
from pathlib import Path

import requests

from anilixy.core.storage import DATA_DIR, load_json, write_json

log = logging.getLogger(__name__)

OFFLINE_DIR = DATA_DIR / "manga"
USER_AGENT = {"User-Agent": "Mozilla/5.0"}
_lock = threading.Lock()


def _media_dir(anilist_id) -> Path:
    return OFFLINE_DIR / str(anilist_id)


def _meta_path(anilist_id) -> Path:
    return _media_dir(anilist_id) / "meta.json"


def _load_meta(anilist_id) -> dict:
    return load_json(_meta_path(anilist_id))


def _save_meta(anilist_id, meta) -> None:
    write_json(_meta_path(anilist_id), meta, indent=2, ensure_ascii=False)


def _chapter_folder(chapter) -> str:
    name = str(chapter.get("attributes", {}).get("chapter") or "chapter")
    name = re.sub(r"[^\w.\- ]+", "", name).strip() or "chapter"
    digest = hashlib.sha1(str(chapter["id"]).encode()).hexdigest()[:8]
    return f"{name} [{digest}]"


def remember_chapters(anilist_id, source_id, chapters) -> None:
    with _lock:
        meta = _load_meta(anilist_id)
        if not meta.get("downloaded"):
            return
        if meta.get("chapters") == chapters and meta.get("source_id") == source_id:
            return
        meta["source_id"] = source_id
        meta["chapters"] = chapters
        _save_meta(anilist_id, meta)


def cached_chapters(anilist_id, source_id) -> list:
    meta = _load_meta(anilist_id)
    if meta.get("source_id") != source_id:
        return []
    downloaded = meta.get("downloaded") or {}
    return [c for c in meta.get("chapters") or [] if c.get("id") in downloaded]


def downloaded_ids(anilist_id) -> set:
    return set(_load_meta(anilist_id).get("downloaded") or {})


def is_downloaded(anilist_id, chapter_id) -> bool:
    return chapter_id in (_load_meta(anilist_id).get("downloaded") or {})


def local_pages(anilist_id, chapter_id):
    info = (_load_meta(anilist_id).get("downloaded") or {}).get(chapter_id)
    if not info:
        return None
    folder = _media_dir(anilist_id) / info["folder"]
    files = sorted(p for p in folder.iterdir() if p.is_file()) if folder.is_dir() else []
    if not files or len(files) < info.get("pages", 0):
        return None
    return [{"index": i, "url": path.as_uri()} for i, path in enumerate(files)]


def read_local(url) -> bytes:
    from urllib.parse import urlparse
    from urllib.request import url2pathname

    return Path(url2pathname(urlparse(url).path)).read_bytes()


def _extension(url, content_type) -> str:
    for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"):
        if url.lower().split("?")[0].endswith(ext):
            return ext
    kind = (content_type or "").split("/")[-1].split(";")[0].strip()
    return f".{kind}" if kind in ("png", "webp", "gif", "avif") else ".jpg"


def download_chapter(anilist_id, source_id, chapter, pages, headers=None, cache=None) -> bool:
    headers = headers or USER_AGENT
    folder_name = _chapter_folder(chapter)
    folder = _media_dir(anilist_id) / folder_name
    folder.mkdir(parents=True, exist_ok=True)
    for page in pages:
        url = page["url"]
        data = (cache or {}).get(url)
        content_type = None
        if data is None:
            for attempt in range(3):
                try:
                    resp = requests.get(url, timeout=30, headers=headers)
                    resp.raise_for_status()
                    data = resp.content
                    content_type = resp.headers.get("content-type")
                    break
                except requests.RequestException:
                    if attempt == 2:
                        log.warning("Could not download %s", url, exc_info=True)
                        return False
        target = folder / f"{page['index'] + 1:04d}{_extension(url, content_type)}"
        target.write_bytes(data)
    with _lock:
        meta = _load_meta(anilist_id)
        meta["source_id"] = source_id
        meta.setdefault("downloaded", {})[chapter["id"]] = {
            "folder": folder_name,
            "pages": len(pages),
            "chapter": chapter.get("attributes", {}).get("chapter"),
        }
        _save_meta(anilist_id, meta)
    return True


def downloads_stats():
    chapters = 0
    size = 0
    if not OFFLINE_DIR.is_dir():
        return 0, 0
    for media in OFFLINE_DIR.iterdir():
        if media.is_dir():
            chapters += len(load_json(media / "meta.json").get("downloaded") or {})
            for path in media.rglob("*"):
                try:
                    if path.is_file():
                        size += path.stat().st_size
                except OSError:
                    pass
    return chapters, size


def clear_downloads() -> None:
    with _lock:
        shutil.rmtree(OFFLINE_DIR, ignore_errors=True)
