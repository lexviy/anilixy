import json
import logging
import os
import select
import socket
import struct
import threading
import time
from pathlib import Path
from urllib.parse import quote

from anilixy.core.storage import CONFIG_DIR

log = logging.getLogger(__name__)


OP_HANDSHAKE = 0
OP_FRAME = 1
OP_CLOSE = 2
OP_PING = 3
OP_PONG = 4

RETRY_INTERVAL = 15.0

DEFAULT_CLIENT_ID = "1563698256058261545"

GITHUB_URL = "https://github.com/lexviy/anilixy"
MIN_INTERVAL = 4.0


def _get_ipc_paths():
    paths = []
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime:
        for i in range(10):
            paths.append(Path(runtime) / f"discord-ipc-{i}")
            paths.append(
                Path(runtime) / "app" / "com.discordapp.Discord" / f"discord-ipc-{i}"
            )
            paths.append(Path(runtime) / "snap.discord" / f"discord-ipc-{i}")

    tmpdir = (
        os.environ.get("TMPDIR")
        or os.environ.get("TMP")
        or os.environ.get("TEMP")
        or "/tmp"
    )
    tmp = Path(tmpdir)
    for i in range(10):
        paths.append(tmp / f"discord-ipc-{i}")
        paths.append(tmp / "snap.discord" / f"discord-ipc-{i}")

    paths.append(Path("/tmp") / "discord-ipc-0")
    return paths


def _get_client_id():
    env_id = os.environ.get("ANILIXY_DISCORD_CLIENT_ID")
    if env_id and str(env_id).strip():
        return str(env_id).strip()

    config = CONFIG_DIR / "discord.json"
    if config.exists():
        try:
            data = json.loads(config.read_text(encoding="utf-8"))
            for key in ("client_id", "id", "application_id"):
                cid = data.get(key)
                if cid and str(cid).strip():
                    return str(cid).strip()
        except Exception:
            log.debug("ignored error", exc_info=True)
    return DEFAULT_CLIENT_ID


class DiscordRPC:
    def __init__(self):
        self.sock = None
        self.connected = False
        self.ready = False
        self.pid = os.getpid()
        self.start_time = int(time.time())
        self.client_id = None
        self._lock = threading.Lock()
        self._covers = {}
        self._pending = set()
        self._current_media = None
        self._redo = None
        self.avatar = None
        self.user = None
        self._last_sent = 0.0
        self._queued = None
        self._timer = None
        self._conn_lock = threading.RLock()
        self.enabled = False
        self._stop = threading.Event()
        self._watcher = None
        self._rbuf = b""
        self._last_payload = None
        self._started = False

    def _encode(self, opcode, payload):
        data = json.dumps(payload).encode("utf-8") if payload is not None else b""
        return struct.pack("<II", opcode, len(data)) + data

    def _send(self, opcode, payload=None):
        if not self.sock:
            return False
        try:
            with self._lock:
                self.sock.sendall(self._encode(opcode, payload))
            return True
        except Exception:
            self.disconnect()
            return False

    def _get_title(self, anime):
        if anime is None:
            return None
        if isinstance(anime, str):
            return anime
        if isinstance(anime, dict):
            t = anime.get("title") or {}
            if isinstance(t, dict):
                title = t.get("english") or t.get("romaji") or t.get("native")
                if title:
                    return title
            if anime.get("name"):
                return anime.get("name")
        return None

    def connect(self):
        with self._conn_lock:
            if self.connected and self.ready:
                return True

            self.client_id = _get_client_id()
            if not self.client_id:
                return False

            sock = None
            for path in _get_ipc_paths():
                candidate = None
                try:
                    if not path.exists():
                        continue
                    candidate = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    candidate.settimeout(2.0)
                    candidate.connect(str(path))
                    candidate.settimeout(None)
                    sock = candidate
                    break
                except Exception:
                    if candidate is not None:
                        try:
                            candidate.close()
                        except Exception:
                            log.debug("ignored error", exc_info=True)
                    continue

            if sock is None:
                return False

            self.sock = sock
            self._rbuf = b""
            try:
                self._send(OP_HANDSHAKE, {"v": 1, "client_id": str(self.client_id)})
                time.sleep(0.2)
                try:
                    self.sock.settimeout(1.0)
                    header = self.sock.recv(8)
                    self.sock.settimeout(None)
                    if len(header) == 8:
                        opcode, length = struct.unpack("<II", header)
                        if length > 0:
                            data = self.sock.recv(length)
                            if data:
                                msg = json.loads(data)
                                if msg.get("evt") == "READY":
                                    self.ready = True
                except Exception:
                    self.ready = True
            except Exception:
                self.disconnect()
                return False

            self.connected = True
            if not self._started:
                self.start_time = int(time.time())
                self._started = True
            if self._last_payload is not None:
                payload = dict(self._last_payload)
                payload["nonce"] = str(time.time())
                self._last_sent = time.monotonic()
                self._send(OP_FRAME, payload)
            else:
                self.update(details="Browsing", state="Main Menu")
            return self.connected

    def start(self):
        self.enabled = True
        self._stop.clear()
        ok = self.connect()
        if self._watcher is None or not self._watcher.is_alive():
            self._watcher = threading.Thread(target=self._watch, daemon=True)
            self._watcher.start()
        return ok

    def stop(self):
        self.enabled = False
        self._stop.set()
        self.disconnect()

    def _watch(self):
        while not self._stop.is_set():
            sock = self.sock
            if sock is None:
                if self.enabled:
                    try:
                        self.connect()
                    except Exception:
                        log.debug("ignored error", exc_info=True)
                self._stop.wait(RETRY_INTERVAL)
                continue
            try:
                ready, _, _ = select.select([sock], [], [], 2.0)
            except (OSError, ValueError):
                self.disconnect()
                continue
            if ready and not self._drain(sock):
                self.disconnect()

    def _drain(self, sock):
        try:
            data = sock.recv(65536)
        except (BlockingIOError, InterruptedError):
            return True
        except OSError:
            return False
        if not data:
            return False
        self._rbuf += data
        while len(self._rbuf) >= 8:
            opcode, length = struct.unpack("<II", self._rbuf[:8])
            if len(self._rbuf) < 8 + length:
                break
            body = self._rbuf[8 : 8 + length]
            self._rbuf = self._rbuf[8 + length :]
            if opcode == OP_CLOSE:
                return False
            if opcode == OP_PING:
                try:
                    self._send(OP_PONG, json.loads(body or b"{}"))
                except Exception:
                    log.debug("ignored error", exc_info=True)
        return True

    def update(
        self,
        details=None,
        state=None,
        large_image=None,
        large_text=None,
        small_image=None,
        small_text=None,
        media_id=None,
        details_url=None,
        state_url=None,
        large_url=None,
        small_url=None,
        buttons=None,
    ):
        self._current_media = media_id

        activity = {
            "timestamps": {"start": self.start_time},
            "instance": True,
        }

        if details:
            activity["details"] = str(details)[:128]
        if state:
            activity["state"] = str(state)[:128]

        assets = {
            "large_image": self.avatar or "logo",
            "large_text": self.user or "Anilixy",
        }
        if large_image:
            limit = 256 if str(large_image).startswith("http") else 32
            assets["large_image"] = str(large_image)[:limit]
        if large_text:
            assets["large_text"] = str(large_text)[:128]
        if small_image:
            limit = 256 if str(small_image).startswith("http") else 32
            assets["small_image"] = str(small_image)[:limit]
        if small_text:
            assets["small_text"] = str(small_text)[:128]
        profile = self._profile_url()
        if not large_image and self.avatar and profile:
            large_url = large_url or profile
        if large_url:
            assets["large_url"] = str(large_url)[:512]
        if small_image and (small_url or profile):
            assets["small_url"] = str(small_url or profile)[:512]
        activity["assets"] = assets

        if details:
            activity["details_url"] = str(details_url or GITHUB_URL)[:512]
        if state and state_url:
            activity["state_url"] = str(state_url)[:512]
        if buttons is None:
            buttons = [{"label": "GitHub", "url": GITHUB_URL}]
        if buttons:
            activity["buttons"] = [
                {"label": str(b["label"])[:32], "url": str(b["url"])[:512]}
                for b in buttons[:2]
            ]

        payload = {
            "cmd": "SET_ACTIVITY",
            "args": {"pid": self.pid, "activity": activity},
            "nonce": str(time.time()),
        }
        return self._send_activity(payload)

    def _profile_url(self):
        return f"https://anilist.co/user/{quote(self.user)}" if self.user else None

    def _send_activity(self, payload):
        self._last_payload = payload
        if not self.sock:
            return False
        wait = MIN_INTERVAL - (time.monotonic() - self._last_sent)
        if wait > 0:
            self._queued = payload
            if self._timer is None:
                self._timer = threading.Timer(wait, self._flush)
                self._timer.daemon = True
                self._timer.start()
            return True
        self._last_sent = time.monotonic()
        return self._send(OP_FRAME, payload)

    def _flush(self):
        self._timer = None
        payload, self._queued = self._queued, None
        if payload is not None:
            self._last_sent = time.monotonic()
            self._send(OP_FRAME, payload)

    def _cover(self, media_id, anime=None):
        if isinstance(anime, dict):
            images = anime.get("coverImage") or {}
            url = images.get("extraLarge") or images.get("large") or images.get("medium")
            if url:
                self._covers[media_id] = url
                return url
        return self._covers.get(media_id) or None

    def _fetch_cover(self, media_id):
        if (
            not isinstance(media_id, int)
            or media_id in self._covers
            or media_id in self._pending
        ):
            return
        self._pending.add(media_id)

        def run():
            url = None
            try:
                from anilixy.anilist.api import fetch_media

                images = (fetch_media(media_id) or {}).get("coverImage") or {}
                url = images.get("extraLarge") or images.get("large")
            except Exception:
                log.debug("ignored error", exc_info=True)
            self._covers[media_id] = url or ""
            self._pending.discard(media_id)
            if url and self._current_media == media_id and self._redo:
                try:
                    self._redo()
                except Exception:
                    log.debug("ignored error", exc_info=True)

        threading.Thread(target=run, daemon=True).start()

    def _media_update(self, anime, details, state, large_text=None, kind="anime"):
        media_id = anime.get("id") if isinstance(anime, dict) else None
        media_url = (
            f"https://anilist.co/{kind}/{media_id}" if isinstance(media_id, int) else None
        )
        buttons = [{"label": "GitHub", "url": GITHUB_URL}]
        if media_url:
            buttons.append({"label": "View on AniList", "url": media_url})
        cover = None
        if media_id is not None:
            cover = self._cover(media_id, anime)
            if cover is None:
                self._fetch_cover(media_id)
        ok = self.update(
            details=details,
            state=state,
            large_image=cover,
            large_text=large_text or state,
            small_image=(self.avatar or "logo") if cover else None,
            small_text=(self.user or "Anilixy") if cover else None,
            media_id=media_id,
            state_url=media_url,
            large_url=media_url,
            buttons=buttons,
        )
        self._redo = lambda: self._media_update(anime, details, state, large_text, kind)
        return ok

    def reading(self, media_id, title=None, progress=None):
        title = str(title or "Anilixy")
        anime = {"id": media_id, "title": {"english": title}}
        state = f"{progress} • {title}" if progress else title
        return self._media_update(
            anime, "Reading", state, large_text=title, kind="manga"
        )

    def viewing(self, anime=None, kind="anime"):
        title = self._get_title(anime)
        if title:
            return self._media_update(anime, "Viewing", str(title), kind=kind)
        return self.update(details="Browsing", state="Anime Page")

    def watching(self, anime=None, episode=None, total=None):
        title = self._get_title(anime) or "Anilixy"

        if episode is not None:
            try:
                ep = int(episode)
                if total:
                    try:
                        tot = int(total)
                        state = f"Episode {ep} / {tot} • {title}"
                    except Exception:
                        state = f"Episode {ep} • {title}"
                else:
                    state = f"Episode {ep} • {title}"
            except Exception:
                state = f"Watching • {title}"
        else:
            state = f"Watching • {title}"

        return self._media_update(anime, "Watching", state, large_text=str(title))

    def browsing(self, screen_name=None, anime=None):
        if screen_name == "MenuScreen":
            return self.update(details="Browsing", state="Main Menu")
        elif screen_name in ("SearchScreen", "MangaSearchScreen", "CharacterSearchScreen", "StaffSearchScreen", "StudioSearchScreen"):
            return self.update(details="Browsing", state="Searching")
        elif screen_name == "AnimeScreen":
            title = self._get_title(anime)
            if title:
                return self.viewing(anime)
            return self.update(details="Browsing", state="Anime Page")
        elif screen_name == "MangaScreen":
            title = self._get_title(anime)
            if title:
                return self.viewing(anime, kind="manga")
            return self.update(details="Browsing", state="Manga/Light Novel")
        elif screen_name == "CharacterScreen":
            if anime and isinstance(anime, dict):
                name = (anime.get("name") or {}).get("full") or (anime.get("name") or {}).get("native")
                if name:
                    return self.update(details="Viewing", state=str(name))
            return self.update(details="Browsing", state="Character")
        elif screen_name == "StaffScreen":
            if anime and isinstance(anime, dict):
                name = (anime.get("name") or {}).get("full") or (anime.get("name") or {}).get("native")
                if name:
                    return self.update(details="Viewing", state=str(name))
            return self.update(details="Browsing", state="Staff")
        elif screen_name == "MyAniListScreen":
            return self.update(details="Browsing", state="My AniList")
        elif screen_name == "KeepWatchingScreen":
            return self.update(details="Browsing", state="Keep Watching")
        elif screen_name == "StudioScreen":
            if anime and isinstance(anime, dict):
                name = anime.get("name")
                if name:
                    return self.update(details="Viewing", state=str(name))
            return self.update(details="Browsing", state="Studios")
        elif screen_name == "ThemeScreen":
            return self.update(details="Browsing", state="Themes")
        elif screen_name == "AnimationScreen":
            return self.update(details="Browsing", state="Animations")
        elif screen_name in ("ListEditorScreen", "FolderPickerScreen"):
            return False
        elif screen_name == "SettingsScreen":
            return self.update(details="Browsing", state="Settings")
        elif screen_name == "LoginScreen":
            return self.update(details="Logging in", state="AniList")
        else:
            return self.update(details="Browsing", state="Anilixy")

    def disconnect(self):
        with self._conn_lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            self._queued = None
            sock, self.sock = self.sock, None
            self.connected = False
            self.ready = False
        if sock is not None:
            try:
                sock.sendall(self._encode(OP_CLOSE, None))
            except Exception:
                log.debug("ignored error", exc_info=True)
            try:
                sock.close()
            except Exception:
                log.debug("ignored error", exc_info=True)
        return True
