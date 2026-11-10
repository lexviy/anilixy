import json
import os
import shutil
import stat
import subprocess
import tempfile
import threading
from pathlib import Path

from anilixy.core import ipc
from anilixy.core.storage import DATA_DIR

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
    "Select anime"*)
        if [ -n "$ANILIXY_SAVED_TITLE" ]; then
            exec awk 'tolower(substr($0, index($0, " ") + 1)) == tolower(ENVIRON["ANILIXY_SAVED_TITLE"]) { print; exit }'
        fi
        exec fzf --reverse --cycle --prompt "$prompt"
        ;;
    *)
        exec fzf --reverse --cycle --prompt "$prompt"
        ;;
esac
"""


ANI_CLI_MISSING = (
    "ani-cli or Git Bash was not found" if ipc.WINDOWS else "ani-cli is not installed"
)


def git_bash() -> Path | None:
    roots = []
    if os.environ.get("GIT_INSTALL_ROOT"):
        roots.append(Path(os.environ["GIT_INSTALL_ROOT"]))
    git = shutil.which("git")
    if git:
        roots += Path(git).resolve().parents
    for variable, folder in (
        ("ProgramW6432", "Git"),
        ("ProgramFiles", "Git"),
        ("ProgramFiles(x86)", "Git"),
        ("LOCALAPPDATA", "Programs/Git"),
    ):
        if os.environ.get(variable):
            roots.append(Path(os.environ[variable]) / folder)
    roots.append(Path.home() / "scoop/apps/git/current")
    for root in roots:
        bash = root / "bin" / "bash.exe"
        if bash.is_file():
            return bash
    return None


def ani_cli_script() -> Path | None:
    folders = [Path(p) for p in os.environ.get("PATH", "").split(os.pathsep) if p]
    folders += [DATA_DIR / "bin", Path.home() / "scoop/apps/ani-cli/current"]
    for folder in folders:
        script = folder / "ani-cli"
        if script.is_file():
            return script
    return None


def mpv_folder() -> Path | None:
    roots = [
        Path(os.environ[variable])
        for variable in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)")
        if os.environ.get(variable)
    ]
    if os.environ.get("LOCALAPPDATA"):
        local = Path(os.environ["LOCALAPPDATA"])
        roots += [local / "Programs", local / "Microsoft/WinGet/Packages"]
    roots.append(Path.home() / "scoop/apps/mpv")
    for root in roots:
        for mpv in root.glob("*/mpv.exe"):
            return mpv.parent
    return None


def ani_cli_command() -> list[str] | None:
    if not ipc.WINDOWS:
        return ["ani-cli"] if shutil.which("ani-cli") else None
    bash = git_bash()
    script = ani_cli_script()
    if bash is None or script is None:
        return None
    return [str(bash), script.as_posix()]


def ani_cli_installed() -> bool:
    return ani_cli_command() is not None


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

    def __init__(self, address, on_watched=None):
        self.address = address
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
            try:
                return ipc.connect(self.address)
            except OSError:
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

            for line in ipc.read_lines(sock):
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
    if ipc.WINDOWS:
        mpv_server = os.path.basename(work_dir)
        address = ipc.pipe_path(mpv_server)
    else:
        mpv_server = address = os.path.join(work_dir, "mpv.sock")

    hist_dir = os.path.join(work_dir, "history")
    hist_file = os.path.join(hist_dir, "ani-hsts")
    os.makedirs(hist_dir, exist_ok=True)

    menu_path = os.path.join(work_dir, "menu.sh")
    with open(menu_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(MENU_SCRIPT)
    os.chmod(menu_path, os.stat(menu_path).st_mode | stat.S_IXUSR)

    env = os.environ.copy()
    if ipc.WINDOWS and not shutil.which("mpv.exe"):
        folder = mpv_folder()
        if folder is not None:
            env["PATH"] = f"{folder}{os.pathsep}{env.get('PATH', '')}"

    env["ANI_CLI_HIST_DIR"] = Path(hist_dir).as_posix()
    env["ANI_CLI_MENU"] = Path(menu_path).as_posix()

    flags = env.get("ANI_CLI_PLAYER_FLAGS", "")
    flags += f" --input-ipc-server={mpv_server}"
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
            cmd = ani_cli_command() + ["--no-detach"]

            open(hist_file, "w", encoding="utf-8").close()

            if plan == "history":
                with open(hist_file, "w", encoding="utf-8", newline="\n") as f:
                    f.write(f"{episode - 1}\t{entry['id']}\t{entry['title']}\n")
                cmd += ["-c"] + HISTORY_SELECT_FLAGS + ani_cli_args()
            elif plan == "exact":
                plan_env["ANI_CLI_EXACT"] = "1"
                plan_env["ANILIXY_SAVED_TITLE"] = entry["title"]
                cmd += ["-e", str(episode)] + ani_cli_args() + [entry["title"]]
            else:
                cmd += ["-e", str(episode)]
                if AUTO_SELECT:
                    cmd += ["-S", "1"]
                cmd += ani_cli_args()
                cmd.append(search_query(title))

            watcher = MpvWatcher(address, on_watched)
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
