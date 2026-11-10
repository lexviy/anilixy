import json
import logging
import re
import threading
import time

import requests

from anilixy.core.storage import CONFIG_DIR, load_json, write_json

log = logging.getLogger(__name__)

SYNC_FILE = CONFIG_DIR / "sync.json"
FILE_NAME = "anilixy-sync.json"
APP = "anilixy-sync"
VERSION = 1
DESCRIPTION = "anilixy and aniliphy progress"
API = "https://api.github.com"
NEW_TOKEN_URL = "https://github.com/settings/tokens/new?scopes=gist&description=anilixy%20sync"

ENTRIES_FILE = CONFIG_DIR / "entries.json"
RESUME_FILE = CONFIG_DIR / "resume.json"
MANGA_MAP_FILE = CONFIG_DIR / "manga_map.json"
MANGA_HISTORY_FILE = CONFIG_DIR / "manga_history.json"
NOVEL_PROGRESS_FILE = CONFIG_DIR / "novel_progress.json"


class SyncError(Exception):
    pass


class GistMissing(SyncError):
    pass


def load_sync() -> dict:
    data = load_json(SYNC_FILE)
    return {
        "token": data.get("token") or "",
        "gist": data.get("gist") or "",
        "auto": data.get("auto", True),
        "last": data.get("last"),
    }


def save_sync(**changes) -> None:
    data = load_sync()
    data.update(changes)
    write_json(SYNC_FILE, data, mode=0o600)


def forget_sync() -> None:
    save_sync(token="", gist="", last=None)


def _github(method, path, token, body=None):
    url = path if path.startswith("http") else API + path
    try:
        response = requests.request(
            method,
            url,
            json=body,
            timeout=20,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "anilixy",
            },
        )
    except requests.RequestException as error:
        raise SyncError("Couldn't reach GitHub") from error
    if response.status_code == 401:
        raise SyncError("GitHub didn't accept the token")
    if response.status_code == 403:
        raise SyncError("The token can't use gists. It needs the gist permission")
    if response.status_code == 404 and path.startswith("/gists/"):
        raise GistMissing("The gist is gone")
    if not 200 <= response.status_code < 300:
        raise SyncError(f"GitHub answered {response.status_code}")
    return response


def find_gist(token, github=_github):
    for page in range(1, 11):
        gists = github("GET", f"/gists?per_page=100&page={page}", token).json()
        for gist in gists:
            if FILE_NAME in (gist.get("files") or {}):
                return gist["id"]
        if len(gists) < 100:
            return None
    return None


def parse_payload(text):
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if not isinstance(data, dict) or data.get("app") != APP:
        return None
    if (data.get("version") or 0) > VERSION:
        raise SyncError("The gist's progress comes from a newer version of aniliphy")
    return {
        "anime": data.get("anime") or {},
        "manga": data.get("manga") or {},
        "novels": data.get("novels") or {},
    }


def empty_payload():
    return {"anime": {}, "manga": {}, "novels": {}}


def read_gist(token, gist_id, github=_github):
    gist = github("GET", f"/gists/{gist_id}", token).json()
    file = (gist.get("files") or {}).get(FILE_NAME)
    if not file:
        return empty_payload()
    text = file.get("content")
    if file.get("truncated") and file.get("raw_url"):
        text = github("GET", file["raw_url"], token).text
    return parse_payload(text or "") or empty_payload()


def _body(payload):
    content = json.dumps({"app": APP, "version": VERSION, **payload}, ensure_ascii=False)
    return {"description": DESCRIPTION, "files": {FILE_NAME: {"content": content}}}


def write_gist(token, gist_id, payload, github=_github):
    github("PATCH", f"/gists/{gist_id}", token, _body(payload))


def create_gist(token, payload, github=_github):
    body = {**_body(payload), "public": False}
    return github("POST", "/gists", token, body).json()["id"]


def _updated(item):
    try:
        return float((item or {}).get("updated") or 0)
    except (TypeError, ValueError):
        return 0.0


def _newer(local, remote):
    if local is None:
        return remote
    if remote is None:
        return local
    return remote if _updated(remote) > _updated(local) else local


def merge(local, remote):
    merged = empty_payload()
    for section, source_key in (("anime", "show"), ("manga", "source"), ("novels", None)):
        mine, theirs = local[section], remote[section]
        for key in set(mine) | set(theirs):
            won = dict(_newer(mine.get(key), theirs.get(key)))
            if source_key and not won.get(source_key):
                known = (mine.get(key) or {}).get(source_key) or (theirs.get(key) or {}).get(source_key)
                if known:
                    won[source_key] = known
            merged[section][key] = won
    return merged


def _title(value):
    if isinstance(value, dict):
        return value.get("english") or value.get("romaji")
    return value or None


def _number(text):
    match = re.search(r"\d+(?:\.\d+)?", str(text or ""))
    return float(match.group()) if match else None


def _clean(record):
    return {key: value for key, value in record.items() if value is not None}


def local_payload():
    entries = load_json(ENTRIES_FILE)
    resumes = load_json(RESUME_FILE)
    manga_map = load_json(MANGA_MAP_FILE)
    history = load_json(MANGA_HISTORY_FILE)
    novels = load_json(NOVEL_PROGRESS_FILE)

    anime = {}
    for key in set(entries) | set(resumes):
        entry = entries.get(key) or {}
        resume = resumes.get(key)
        record = {
            "title": _title(resume.get("title")) if resume else entry.get("title"),
            "show": entry.get("id"),
            "updated": _updated(resume),
        }
        if resume:
            record.update(
                episode=float(resume["episode"]),
                position=round(float(resume.get("position") or 0), 1),
                duration=round(float(resume["duration"]), 1) if resume.get("duration") else None,
            )
        anime[key] = _clean(record)

    manga = {}
    for key in set(manga_map) | set(history):
        last = history.get(key) or {}
        chapter = last.get("chapter_number")
        record = {
            "title": _title(last.get("title")),
            "source": manga_map.get(key),
            "chapter_id": last.get("chapter_id"),
            "chapter": str(chapter) if chapter is not None else None,
            "number": _number(chapter),
            "page": int(last.get("page") or 0),
            "updated": _updated(last),
        }
        manga[key] = _clean(record)

    shared = {key: value for key, value in novels.items() if isinstance(value, dict) and "books" in value}
    return {"anime": anime, "manga": manga, "novels": shared}


def _episode(value):
    value = float(value)
    return int(value) if value.is_integer() else value


def _same(old, record, place_keys, source_key):
    if record == old:
        return True
    if old is None or any(record.get(k) is not None for k in place_keys):
        return False
    return not any(old.get(k) is not None for k in place_keys) and old.get(source_key) == record.get(source_key)


def apply(local, merged):
    entries = load_json(ENTRIES_FILE)
    resumes = load_json(RESUME_FILE)
    manga_map = load_json(MANGA_MAP_FILE)
    history = load_json(MANGA_HISTORY_FILE)
    novels = load_json(NOVEL_PROGRESS_FILE)
    counts = {"anime": 0, "manga": 0, "novels": 0}

    for key, record in merged["anime"].items():
        if _same(local["anime"].get(key), record, ("episode",), "show"):
            continue
        counts["anime"] += 1
        show = record.get("show")
        old_entry = entries.get(key) or {}
        if show and old_entry.get("id") != show:
            entries[key] = {"id": show, "title": record.get("title") or show}
        old = resumes.get(key) or {}
        if record.get("episode") is None:
            resumes.pop(key, None)
        else:
            title = record.get("title")
            resumes[key] = {
                "episode": _episode(record["episode"]),
                "position": float(record.get("position") or 0),
                "duration": record.get("duration"),
                "title": old.get("title") or {"romaji": title, "english": title},
                "episodes": old.get("episodes"),
                "updated": _updated(record),
            }

    for key, record in merged["manga"].items():
        if _same(local["manga"].get(key), record, ("chapter_id", "chapter"), "source"):
            continue
        counts["manga"] += 1
        if record.get("source"):
            manga_map[key] = record["source"]
        if not record.get("chapter_id") and not record.get("chapter"):
            history.pop(key, None)
        else:
            history[key] = {
                "chapter_id": record.get("chapter_id"),
                "chapter_number": record.get("chapter") or record.get("number"),
                "page": int(record.get("page") or 0),
                "title": record.get("title") or (history.get(key) or {}).get("title"),
                "updated": _updated(record),
            }

    for key, media in merged["novels"].items():
        if media == local["novels"].get(key):
            continue
        counts["novels"] += 1
        novels[key] = media

    if counts["anime"]:
        write_json(ENTRIES_FILE, entries)
        write_json(RESUME_FILE, resumes)
    if counts["manga"]:
        write_json(MANGA_MAP_FILE, manga_map, indent=2)
        write_json(MANGA_HISTORY_FILE, history, indent=2)
    if counts["novels"]:
        write_json(NOVEL_PROGRESS_FILE, novels)
    return counts


_running = threading.Lock()


def sync(token=None, github=_github):
    with _running:
        return _sync(token, github)


def _sync(token, github):
    settings = load_sync()
    token = (token or settings["token"]).strip()
    if not token:
        raise SyncError("No GitHub token")
    gist_id = settings["gist"] or find_gist(token, github)
    try:
        remote = read_gist(token, gist_id, github) if gist_id else empty_payload()
    except GistMissing:
        gist_id = find_gist(token, github)
        remote = read_gist(token, gist_id, github) if gist_id else empty_payload()
    local = local_payload()
    merged = merge(local, remote)
    counts = apply(local, merged)
    if gist_id is None:
        gist_id = create_gist(token, merged, github)
    elif merged != remote:
        write_gist(token, gist_id, merged, github)
    save_sync(token=token, gist=gist_id, last=time.time())
    changed = [f"{n} {kind}" for kind, n in counts.items() if n]
    if not changed:
        return "Synced. Nothing new from the phone"
    return "Synced. New places for " + ", ".join(changed)
