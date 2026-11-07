import json
import os
import sys
import tempfile
import time
from pathlib import Path


def _env_dir(var, fallback):
    value = os.environ.get(var)
    return Path(value) if value else Path.home() / fallback


if sys.platform == "win32":
    CONFIG_DIR = _env_dir("APPDATA", "AppData/Roaming") / "anilixy"
    DATA_DIR = _env_dir("LOCALAPPDATA", "AppData/Local") / "anilixy"
    CACHE_DIR = DATA_DIR / "cache"
else:
    CONFIG_DIR = Path.home() / ".config" / "anilixy"
    CACHE_DIR = _env_dir("XDG_CACHE_HOME", ".cache") / "anilixy"
    DATA_DIR = _env_dir("XDG_DATA_HOME", ".local/share") / "anilixy"


def load_json(path, default=None):
    if default is None:
        default = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return default
    return data if isinstance(data, type(default)) else default


def _replace(source, target) -> None:
    for delay in (0.02, 0.05, 0.1, 0.25):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if sys.platform != "win32":
                raise
            time.sleep(delay)
    os.replace(source, target)


def write_json(path, data, indent=4, mode=0o644, **dump_kwargs) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=indent, **dump_kwargs)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        _replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
