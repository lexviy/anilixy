import logging
import os
from logging.handlers import RotatingFileHandler

from anilixy.core.storage import CACHE_DIR

LOG_FILE = CACHE_DIR / "anilixy.log"


def setup_logging() -> None:
    level = logging.DEBUG if os.environ.get("ANILIXY_DEBUG") else logging.INFO
    root = logging.getLogger("anilixy")
    if root.handlers:
        return
    root.setLevel(level)
    root.propagate = False
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            LOG_FILE, maxBytes=1_000_000, backupCount=2, encoding="utf-8"
        )
    except OSError:
        return
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    root.addHandler(handler)
