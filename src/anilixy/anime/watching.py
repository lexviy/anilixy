import logging
import time

import requests

from anilixy.anilist.api import save_progress, start_media
from anilixy.anime.entries import load_entry, save_entry
from anilixy.anime.player import ANI_CLI_MISSING, ani_cli_installed, play
from anilixy.anime.progress import save_local_progress
from anilixy.anime.resume import clear_resume, format_time, load_resume, save_resume
from anilixy.core.settings import load_autoplay_delay

log = logging.getLogger(__name__)


MIN_RESUME_SECONDS = 10

AUTOPLAY = True


def countdown(seconds, next_episode) -> bool:
    try:
        for left in range(seconds, 0, -1):
            print(
                f"\rEpisode {next_episode} starts in {left}s (Ctrl+C to stop)  ",
                end="",
                flush=True,
            )
            time.sleep(1)
        print("\r" + " " * 50 + "\r", end="", flush=True)
        return True
    except KeyboardInterrupt:
        print("\nAutoplay stopped.")
        return False


def watch(app, anime, episode) -> None:
    if not ani_cli_installed():
        app.notify(ANI_CLI_MISSING, severity="error")
        return

    media_id = anime["id"]
    title = anime["title"]["romaji"] or anime["title"]["english"] or ""
    total = anime["episodes"]
    messages = []

    if not getattr(app, "guest", False) and getattr(app, "token", None):
        try:
            new_status = start_media(app.token, media_id)
        except Exception:
            messages.append(("Could not update your AniList status", "warning"))
        else:
            if new_status:
                clear_resume(media_id)
                label = "Rewatching" if new_status == "REPEATING" else "Watching"
                messages.append(
                    (f"AniList status: {label} (progress reset)", "information")
                )

    rpc = getattr(app, "rpc", None)
    if rpc is not None:
        try:
            rpc.watching(anime, episode, total)
        except Exception:
            log.debug("ignored error", exc_info=True)

    with app.suspend():
        first = True
        while True:
            if rpc is not None:
                try:
                    rpc.watching(anime, episode, total)
                except Exception:
                    log.debug("ignored error", exc_info=True)
            try:
                result = play_episode(app, anime, title, episode, first, messages)
            except KeyboardInterrupt:
                messages.append(("Stopped", "warning"))
                break

            if not first and result["position"] is None:
                messages.append(
                    (
                        f"Episode {episode} could not be played (not available yet?)",
                        "warning",
                    )
                )

            if result.get("previous"):
                if episode <= 1:
                    messages.append(("Already at the first episode", "warning"))
                    break
                if load_entry(media_id) is None:
                    messages.append(
                        (
                            "Going back needs a saved ani-cli choice for this anime",
                            "warning",
                        )
                    )
                    break
                episode -= 1
                first = False
                continue

            if not (AUTOPLAY and (result["finished"] or result["skipped"])):
                break
            if total and episode >= total:
                messages.append(("That was the last episode", "information"))
                break
            if load_entry(media_id) is None:
                messages.append(
                    ("Autoplay needs a saved ani-cli choice for this anime", "warning")
                )
                break
            delay = load_autoplay_delay()
            if delay > 0 and not countdown(delay, episode + 1):
                break

            episode += 1
            first = False

    if rpc is not None:
        try:
            rpc.viewing(anime)
        except Exception:
            log.debug("ignored error", exc_info=True)

    for text, severity in messages:
        app.notify(text, severity=severity)


def play_episode(app, anime, title, episode, first, messages):
    media_id = anime["id"]
    entry = load_entry(media_id)
    outcome = {"state": None}

    start = None
    resume = load_resume(media_id)
    if (
        resume
        and resume["episode"] == episode
        and resume["position"] >= MIN_RESUME_SECONDS
    ):
        start = resume["position"]

    def on_watched():
        try:
            if app.guest:
                saved = save_local_progress(anime, episode)
            else:
                saved = save_progress(app.token, media_id, episode, anime["episodes"])
            outcome["state"] = "saved" if saved else "skipped"
        except requests.RequestException:
            outcome["state"] = "error"

    result = play(title, episode, on_watched, entry, start, interactive=first)

    used = result["entry"]
    position = result["position"]

    if used and used != entry:
        save_entry(media_id, used)
        if entry is None:
            messages.append(("Saved your ani-cli choice for this anime", "information"))
        else:
            messages.append(("Updated your saved ani-cli choice", "warning"))

    if not app.guest:
        if outcome["state"] == "saved":
            messages.append(
                (f"AniList updated: {title} - episode {episode}", "information")
            )
        elif outcome["state"] == "skipped":
            messages.append(
                (
                    "AniList unchanged (you are already at or past that episode)",
                    "information",
                )
            )
        elif outcome["state"] == "error":
            messages.append(("Could not update AniList", "error"))

    moving_on = result["finished"] or result["skipped"]
    if outcome["state"] in ("saved", "skipped") or moving_on:
        clear_resume(media_id)
    elif position is not None and position >= MIN_RESUME_SECONDS:
        save_resume(anime, episode, position, result["duration"])
        messages.append(
            (
                f"Saved your place: episode {episode} at {format_time(position)}",
                "information",
            )
        )

    return result
