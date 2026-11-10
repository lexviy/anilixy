import logging
import os
import re
import shutil
import subprocess
import sys
from importlib import metadata

import requests

log = logging.getLogger(__name__)

REPO = "lexviy/anilixy"
LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"


class UpdateError(Exception):
    pass


def current_version() -> str:
    try:
        return metadata.version("anilixy")
    except metadata.PackageNotFoundError:
        return "unknown"


def _parts(version: str) -> tuple:
    return tuple(int(n) for n in re.findall(r"\d+", version)[:3])


def is_newer(latest: str, current: str) -> bool:
    if current == "unknown":
        return True
    return _parts(latest) > _parts(current)


def latest_release() -> dict:
    try:
        response = requests.get(
            LATEST,
            timeout=15,
            headers={"Accept": "application/vnd.github+json", "User-Agent": "anilixy"},
        )
    except requests.RequestException as error:
        raise UpdateError("Couldn't reach GitHub") from error
    if response.status_code != 200:
        raise UpdateError(f"GitHub answered {response.status_code}")
    tag = response.json().get("tag_name") or ""
    if not _parts(tag):
        raise UpdateError("The newest release has no version number")
    return {
        "version": tag.lstrip("vV"),
        "tag": tag,
        "source": f"https://github.com/{REPO}/archive/refs/tags/{tag}.zip",
        "page": response.json().get("html_url") or RELEASES_PAGE,
    }


def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _in_pipx() -> bool:
    return "pipx" in os.path.normpath(sys.prefix).lower().split(os.sep)


def install_command(source: str) -> list:
    if _in_pipx():
        pipx = shutil.which("pipx")
        runner = [pipx] if pipx else [getattr(sys, "_base_executable", None) or "python", "-m", "pipx"]
        return runner + ["runpip", "anilixy", "install", "--upgrade", source]
    return [sys.executable, "-m", "pip", "install", "--upgrade", source]


def install(release: dict) -> None:
    command = install_command(release["source"])
    log.info("Updating with: %s", " ".join(command))
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=600,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise UpdateError(f"The update couldn't run: {error}") from error
    if result.returncode != 0:
        log.warning("Update failed:\n%s\n%s", result.stdout, result.stderr)
        last = (result.stderr or result.stdout).strip().splitlines()
        raise UpdateError("The update failed" + (f": {last[-1]}" if last else ""))


def restart() -> None:
    if frozen():
        os.execv(sys.executable, [sys.executable])
    code = "from anilixy.main import main; main()"
    os.execv(sys.executable, [sys.executable, "-c", code])
