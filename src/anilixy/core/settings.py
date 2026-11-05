from pathlib import Path

from anilixy.core.storage import CONFIG_DIR, load_json, write_json
from anilixy.ui.themes import DEFAULT_THEME

DEFAULT_LN_FOLDER = Path.home() / "Downloads" / "anilixy"
SETTINGS_FILE = CONFIG_DIR / "settings.json"


def _load() -> dict:
    return load_json(SETTINGS_FILE)


def _save(data: dict) -> None:
    write_json(SETTINGS_FILE, data)


def load_theme() -> str:
    return _load().get("theme", DEFAULT_THEME)


def save_theme(name: str) -> None:
    data = _load()
    data["theme"] = name
    _save(data)


def load_animation() -> str:
    return _load().get("animation", "rain")


def save_animation(kind: str) -> None:
    data = _load()
    data["animation"] = kind
    _save(data)


def load_discord() -> bool:
    return bool(_load().get("discord", True))


def save_discord(value: bool) -> None:
    data = _load()
    data["discord"] = bool(value)
    _save(data)


def load_ln_folder() -> Path:
    saved = _load().get("ln_folder")
    return Path(saved).expanduser() if saved else DEFAULT_LN_FOLDER


def save_ln_folder(path) -> None:
    data = _load()
    data["ln_folder"] = str(path)
    _save(data)


def load_guest() -> bool:
    return bool(_load().get("guest", False))


def save_guest(value: bool) -> None:
    data = _load()
    data["guest"] = bool(value)
    _save(data)

AUTOPLAY_DELAY_DEFAULT = 3
AUTOPLAY_DELAY_MAX = 30


def load_autoplay_delay() -> int:
    value = _load().get("autoplay_delay", AUTOPLAY_DELAY_DEFAULT)
    try:
        return min(AUTOPLAY_DELAY_MAX, max(0, int(value)))
    except (TypeError, ValueError):
        return AUTOPLAY_DELAY_DEFAULT


def save_autoplay_delay(value) -> None:
    data = _load()
    data["autoplay_delay"] = min(AUTOPLAY_DELAY_MAX, max(0, int(value)))
    _save(data)


QUALITIES = ("best", "1080p", "720p", "480p", "360p", "worst")


def load_quality() -> str:
    value = _load().get("quality", "best")
    return value if value in QUALITIES else "best"


def save_quality(value: str) -> None:
    if value not in QUALITIES:
        return
    data = _load()
    data["quality"] = value
    _save(data)


def load_dub() -> bool:
    return bool(_load().get("dub", False))


def save_dub(value: bool) -> None:
    data = _load()
    data["dub"] = bool(value)
    _save(data)


def load_notifications() -> bool:
    return bool(_load().get("notifications", True))


def save_notifications(value: bool) -> None:
    data = _load()
    data["notifications"] = bool(value)
    _save(data)
