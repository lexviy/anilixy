import logging
import shutil
import subprocess

from anilixy.anilist.api import fetch_reading, fetch_watching
from anilixy.anime.new_episodes import check_new
from anilixy.core.settings import load_notifications
from anilixy.core.storage import CONFIG_DIR, load_json, write_json
from anilixy.manga import new_chapters

log = logging.getLogger(__name__)

NOTIFIED_FILE = CONFIG_DIR / "notified.json"


def desktop_notify(title: str, body: str) -> bool:
    if not load_notifications():
        return False
    command = shutil.which("notify-send")
    if not command:
        return False
    try:
        subprocess.Popen(
            [command, "--app-name=anilixy", title, body],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return True
    except OSError:
        log.warning("notify-send failed", exc_info=True)
        return False


def _first_time(notified, kind, media_id, value) -> bool:
    key = f"{kind}:{media_id}"
    if notified.get(key) is not None and value <= notified[key]:
        return False
    notified[key] = value
    return True


def _title(media) -> str:
    titles = media.get("title") or {}
    return titles.get("english") or titles.get("romaji") or "?"


def check_updates(token, user_id) -> list[tuple[str, str]]:
    notified = load_json(NOTIFIED_FILE)
    messages = []

    try:
        watching = fetch_watching(token, user_id)
    except Exception:
        log.warning("Could not check new episodes", exc_info=True)
        watching = []
    media_by_id = {str(e["media"]["id"]): e["media"] for e in watching}
    for key, episode in check_new(watching).items():
        if _first_time(notified, "ep", key, episode):
            messages.append(("New episode", f"{_title(media_by_id[key])} — episode {episode}"))

    try:
        reading = fetch_reading(token, user_id)
    except Exception:
        log.warning("Could not load the reading list", exc_info=True)
        reading = []
    media_by_id = {str(e["media"]["id"]): e["media"] for e in reading}
    for key, chapter in new_chapters.check(reading)["fresh"].items():
        if _first_time(notified, "ch", key, chapter):
            messages.append(("New chapter", f"{_title(media_by_id[key])} — chapter {chapter:g}"))

    if messages:
        write_json(NOTIFIED_FILE, notified, indent=2)
    return messages
