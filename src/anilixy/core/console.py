import os
import subprocess
import sys
from pathlib import Path

APP_TITLE = "Anilixy"


def open_in_own_window() -> None:
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return
    terminal = Path(sys.executable).parent / "terminal" / "wt.exe"
    if os.environ.get("WT_SESSION") or not terminal.is_file():
        return
    command = [str(terminal), "-w", "new", "--maximized"]
    command += ["new-tab", "--title", APP_TITLE, "--", sys.executable]
    env = {**os.environ, "PYINSTALLER_RESET_ENVIRONMENT": "1"}
    try:
        subprocess.Popen(command, env=env)
    except OSError:
        return
    sys.exit(0)


def set_window_title() -> None:
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.kernel32.SetConsoleTitleW(APP_TITLE)


def enable_vt_output() -> None:
    if sys.platform != "win32":
        return
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetStdHandle.restype = ctypes.c_void_p
    handle = kernel32.GetStdHandle(-11)
    mode = ctypes.c_ulong()
    if kernel32.GetConsoleMode(ctypes.c_void_p(handle), ctypes.byref(mode)):
        enable_virtual_terminal_processing = 0x0004
        kernel32.SetConsoleMode(
            ctypes.c_void_p(handle), mode.value | enable_virtual_terminal_processing
        )
