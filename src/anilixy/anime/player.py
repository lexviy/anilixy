import json
import os
import shutil
import socket
import stat
import subprocess
import tempfile
import threading

AUTO_SELECT = False

SHORT_QUERY = True

EXTRA_ARGS = []


def ani_cli_args() -> list[str]:
    from anilixy.core.settings import load_dub, load_quality

    args = []
    quality = load_quality()
    if quality != "best":
        args += ["-q", quality]
    if load_dub():
        args.append("--dub")
    return args + EXTRA_ARGS

HISTORY_SELECT_FLAGS = ["-S", "1"]

WATCHED_PERCENT = 80

FINISHED_PERCENT = 90

SKIP_KEYS = ["n"]
PREV_KEYS = ["p"]

MENU_SCRIPT = """#!/bin/sh
prompt=""
for prompt; do :; done
case "$prompt" in
    "Playing episode"*)
        cat >/dev/null
        echo quit
        ;;
    *)
        exec fzf --reverse --cycle --prompt "$prompt"
        ;;
esac
"""


def ani_cli_installed() -> bool:
    return shutil.which("ani-cli") is not None


def search_query(title: str) -> str:
    if SHORT_QUERY:
        short = title.split(":")[0].strip()
        if short:
            return short
    return title


class MpvWatcher:
    PROPERTIES = {
        "time-pos": "position",
        "percent-pos": "percent",
        "duration": "duration",
    }
    SKIP_MESSAGE = "anilixy-next"
    PREV_MESSAGE = "anilixy-prev"

    def __init__(self, sock_path, on_watched=None):
        self.sock_path = sock_path
        self.on_watched = on_watched
        self.position = None
        self.percent = None
        self.duration = None
        self.reached_end = False
        self.skipped = False
        self.previous = False
        self._sock = None
        self._fired = False
        self._callback_thread = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    @property
    def finished(self):
        return self.reached_end and (self.percent or 0) >= FINISHED_PERCENT

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()

    def finish(self):
        self.stop()
        self._thread.join(timeout=3)
        if self._callback_thread is not None:
            self._callback_thread.join(timeout=15)

    def _connect(self):
        while not self._stop.is_set():
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                sock.connect(self.sock_path)
                return sock
            except OSError:
                sock.close()
                self._stop.wait(0.3)
        return None

    def _send(self, *command):
        self._sock.sendall((json.dumps({"command": list(command)}) + "\n").encode())

    def _run(self):
        sock = self._connect()
        if sock is None:
            return
        self._sock = sock

        try:
            for request_id, name in enumerate(self.PROPERTIES, start=1):
                self._send("observe_property", request_id, name)

            for key in SKIP_KEYS:
                self._send("keybind", key, f"script-message {self.SKIP_MESSAGE}")
            for key in PREV_KEYS:
                self._send("keybind", key, f"script-message {self.PREV_MESSAGE}")
            self._send("show-text", "N: next episode | P: previous episode", 4000)

            with sock.makefile("r") as reader:
                for line in reader:
                    self._handle(line)
        except OSError:
            pass
        finally:
            sock.close()

    def _handle(self, line):
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            return

        event = message.get("event")

        if event == "end-file":
            if message.get("reason") == "eof":
                self.reached_end = True
            return

        if event == "client-message":
            if self.skipped or self.previous:
                return
            args = message.get("args")
            if args == [self.SKIP_MESSAGE]:
                self.skipped = True
                text = "Next episode..."
            elif args == [self.PREV_MESSAGE]:
                self.previous = True
                text = "Previous episode..."
            else:
                return
            try:
                self._send("show-text", text, 3000)
                self._send("quit")
            except OSError:
                pass
            return

        if event != "property-change" or message.get("data") is None:
            return

        attribute = self.PROPERTIES.get(message.get("name"))
        if attribute is None:
            return
        setattr(self, attribute, float(message["data"]))

        if (
            attribute == "percent"
            and self.percent >= WATCHED_PERCENT
            and not self._fired
            and self.on_watched is not None
        ):
            self._fired = True
            self._callback_thread = threading.Thread(
                target=self.on_watched, daemon=True
            )
            self._callback_thread.start()


def read_history_entry(hist_file):
    try:
        with open(hist_file, "r", encoding="utf-8") as f:
            for line in f:
                parts = line.rstrip("\n").split("\t")
                if len(parts) >= 3 and parts[1]:
                    return {"id": parts[1], "title": parts[2]}
    except OSError:
        pass
    return None


def play(title: str, episode: int, on_watched=None, entry=None, start=None, interactive=True):
    work_dir = tempfile.mkdtemp(prefix="anilixy-")
    sock_path = os.path.join(work_dir, "mpv.sock")

    hist_dir = os.path.join(work_dir, "history")
    hist_file = os.path.join(hist_dir, "ani-hsts")
    os.makedirs(hist_dir, exist_ok=True)

    menu_path = os.path.join(work_dir, "menu.sh")
    with open(menu_path, "w", encoding="utf-8") as f:
        f.write(MENU_SCRIPT)
    os.chmod(menu_path, os.stat(menu_path).st_mode | stat.S_IXUSR)

    env = os.environ.copy()
    env["ANI_CLI_HIST_DIR"] = hist_dir
    env["ANI_CLI_MENU"] = menu_path

    flags = env.get("ANI_CLI_PLAYER_FLAGS", "")
    flags += f" --input-ipc-server={sock_path}"
    if start:
        flags += f" --start={start:.1f}"
    env["ANI_CLI_PLAYER_FLAGS"] = flags.strip()

    plans = []
    if entry is not None:
        if episode >= 2:
            plans.append("history")
        plans.append("exact")
    if interactive:
        plans.append("search")

    if not plans:
        shutil.rmtree(work_dir, ignore_errors=True)
        return {
            "code": 1,
            "entry": None,
            "plan": None,
            "saved_failed": False,
            "finished": False,
            "skipped": False,
            "previous": False,
            "position": None,
            "duration": None,
            "percent": None,
        }

    try:
        for plan in plans:
            plan_env = dict(env)
            cmd = ["ani-cli", "--no-detach"]

            open(hist_file, "w", encoding="utf-8").close()

            if plan == "history":
                with open(hist_file, "w", encoding="utf-8") as f:
                    f.write(f"{episode - 1}\t{entry['id']}\t{entry['title']}\n")
                cmd += ["-c"] + HISTORY_SELECT_FLAGS + ani_cli_args()
            elif plan == "exact":
                plan_env["ANI_CLI_EXACT"] = "1"
                cmd += ["-e", str(episode)] + ani_cli_args() + [entry["title"]]
            else:
                cmd += ["-e", str(episode)]
                if AUTO_SELECT:
                    cmd += ["-S", "1"]
                cmd += ani_cli_args()
                cmd.append(search_query(title))

            watcher = MpvWatcher(sock_path, on_watched)
            watcher.start()
            try:
                code = subprocess.run(cmd, env=plan_env).returncode
            finally:
                watcher.finish()

            if code == 0 or watcher.position is not None:
                break

        used = read_history_entry(hist_file)
        if used is None and plan != "search" and code == 0:
            used = entry

        return {
            "code": code,
            "entry": used,
            "plan": plan,
            "saved_failed": entry is not None and plan == "search",
            "finished": watcher.finished,
            "skipped": watcher.skipped,
            "previous": watcher.previous,
            "position": watcher.position,
            "duration": watcher.duration,
            "percent": watcher.percent,
        }
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
