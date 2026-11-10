import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
NAME = "anilixy"
WINDOWS = sys.platform == "win32"
PACKAGE = DIST / ("anilixy-windows-x64" if WINDOWS else "anilixy-bundle")

PYINSTALLER_OPTIONS = [
    "--collect-data=anilixy",
    "--copy-metadata=anilixy",
    "--collect-submodules=anilixy",
    "--collect-submodules=textual",
    "--collect-submodules=bs4",
    "--collect-all=textual_image",
]

INSTALL_DEPENDENCIES_CMD = """@echo off
powershell -ExecutionPolicy Bypass -File "%~dp0install.ps1" -DependenciesOnly
pause
"""

SMOKE_SECONDS = 20

TERMINAL_VERSION = "1.25.2733.0"
TERMINAL_SHA256 = "bf3ef2012f6c44d8340a4c58125acc9498d19b580f9890dc043cdf831852e796"
TERMINAL_URL = (
    f"https://github.com/microsoft/terminal/releases/download/v{TERMINAL_VERSION}"
    f"/Microsoft.WindowsTerminal_{TERMINAL_VERSION}_x64.zip"
)
TERMINAL_SETTINGS = {
    "alwaysShowTabs": False,
    "showTabsInTitlebar": False,
    "theme": "dark",
    "profiles": {
        "defaults": {
            "padding": "0",
            "scrollbarState": "hidden",
            "bellStyle": "none",
        },
        "list": [],
    },
}


def build(work: Path) -> Path:
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--console",
            f"--name={NAME}",
            f"--icon={ROOT / 'assets' / f'{NAME}.ico'}",
            f"--distpath={work / 'dist'}",
            f"--workpath={work / 'build'}",
            f"--specpath={work}",
            *PYINSTALLER_OPTIONS,
            str(ROOT / "src" / NAME / "__main__.py"),
        ],
        check=True,
    )
    return work / "dist" / NAME


def smoke_test(executable: Path, home: Path) -> None:
    env = {
        **os.environ,
        "TEXTUAL_DRIVER": "textual.drivers.headless_driver:HeadlessDriver",
        "WT_SESSION": "smoke-test",
    }
    for variable in (
        "HOME",
        "USERPROFILE",
        "APPDATA",
        "LOCALAPPDATA",
        "XDG_CACHE_HOME",
        "XDG_DATA_HOME",
    ):
        env[variable] = str(home)
    try:
        result = subprocess.run(
            [str(executable)],
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=SMOKE_SECONDS,
        )
    except subprocess.TimeoutExpired:
        print(f"Smoke test passed: still running after {SMOKE_SECONDS}s")
        return
    print(result.stdout[-4000:])
    print(result.stderr[-4000:], file=sys.stderr)
    sys.exit(f"Smoke test failed: {NAME} exited with code {result.returncode}")


def add_terminal(target: Path) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        archive = Path(temporary) / "terminal.zip"
        urllib.request.urlretrieve(TERMINAL_URL, archive)
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        if digest != TERMINAL_SHA256:
            sys.exit(f"Windows Terminal download has the wrong hash: {digest}")
        unpacked = Path(temporary) / "unpacked"
        with zipfile.ZipFile(archive) as file:
            file.extractall(unpacked)
        shutil.move(next(unpacked.iterdir()), target)

    if not (target / "wt.exe").is_file():
        sys.exit("wt.exe not found in the Windows Terminal download")
    (target / ".portable").touch()
    (target / "settings").mkdir()
    (target / "settings" / "settings.json").write_text(
        json.dumps(TERMINAL_SETTINGS, indent=4)
    )


def main() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        work = Path(temporary)
        bundle = build(work)
        smoke_test(bundle / (f"{NAME}.exe" if WINDOWS else NAME), work)

        shutil.rmtree(PACKAGE, ignore_errors=True)
        PACKAGE.parent.mkdir(exist_ok=True)
        shutil.copytree(bundle, PACKAGE / NAME)

    if WINDOWS:
        add_terminal(PACKAGE / NAME / "terminal")
    shutil.copy2(ROOT / "install.ps1", PACKAGE / NAME)
    command_file = PACKAGE / NAME / "install-dependencies.cmd"
    with open(command_file, "w", newline="\r\n") as file:
        file.write(INSTALL_DEPENDENCIES_CMD)

    archive = shutil.make_archive(str(PACKAGE), "zip", PACKAGE)
    print(f"Created {archive}")


if __name__ == "__main__":
    main()
