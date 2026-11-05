import hashlib
import io
import logging
import threading
from collections import OrderedDict

import requests
from PIL import Image as PILImage

from anilixy.core.storage import CACHE_DIR

log = logging.getLogger(__name__)


COVER_CACHE_DIR = CACHE_DIR / "covers"


COVER_MEMORY_LIMIT = 200


_cover_memory = OrderedDict()


_cover_lock = threading.Lock()


def _cover_path(url):
    return COVER_CACHE_DIR / hashlib.sha1(url.encode("utf-8")).hexdigest()


def load_cover(url):
    path = _cover_path(url)
    try:
        with PILImage.open(path) as image:
            return image.convert("RGB")
    except OSError:
        pass

    response = requests.get(url, timeout=5, headers={"User-Agent": "anilixy"})
    response.raise_for_status()
    data = response.content
    image = PILImage.open(io.BytesIO(data)).convert("RGB")
    try:
        COVER_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    except OSError:
        pass
    return image


def cached_cover(url):
    if not url:
        return None
    with _cover_lock:
        image = _cover_memory.get(url)
        if image is not None:
            _cover_memory.move_to_end(url)
        return image


def safe_cover(url):
    if not url:
        return None
    image = cached_cover(url)
    if image is not None:
        return image
    try:
        image = load_cover(url)
    except (requests.RequestException, OSError):
        return None
    with _cover_lock:
        _cover_memory[url] = image
        while len(_cover_memory) > COVER_MEMORY_LIMIT:
            _cover_memory.popitem(last=False)
    return image


def cover_cache_stats():
    count = 0
    size = 0
    if COVER_CACHE_DIR.is_dir():
        for path in COVER_CACHE_DIR.iterdir():
            try:
                if path.is_file():
                    size += path.stat().st_size
                    count += 1
            except OSError:
                pass
    return count, size


def clear_cover_cache():
    with _cover_lock:
        _cover_memory.clear()
    count = 0
    size = 0
    if COVER_CACHE_DIR.is_dir():
        for path in COVER_CACHE_DIR.iterdir():
            try:
                if path.is_file():
                    file_size = path.stat().st_size
                    path.unlink()
                    size += file_size
                    count += 1
            except OSError:
                pass
    return count, size


def format_size(size) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024


def cell_aspect() -> float:
    try:
        from textual_image._terminal import get_cell_size

        size = get_cell_size()
        if size.width > 0 and size.height > 0:
            return size.height / size.width
    except Exception:
        log.debug("ignored error", exc_info=True)
    return 2.0


def square_fit(image, cols):
    try:
        from textual_image._terminal import get_cell_size

        size = get_cell_size()
        cell_w = size.width
        if cell_w <= 0:
            raise ValueError
    except Exception:
        cell_w = 10
    side = max(1, cols * cell_w)
    return image.resize((side, side), PILImage.Resampling.LANCZOS)


def fit_cover(cover, cols, rows):
    try:
        from textual_image._terminal import get_cell_size

        size = get_cell_size()
        cell_w, cell_h = size.width, size.height
        if cell_w <= 0 or cell_h <= 0:
            raise ValueError
    except Exception:
        cell_w, cell_h = 10, 20
    scale = min(cols * cell_w / cover.width, rows * cell_h / cover.height)
    if scale >= 1:
        return cover
    size = (max(1, round(cover.width * scale)), max(1, round(cover.height * scale)))
    return cover.resize(size, PILImage.Resampling.LANCZOS)
