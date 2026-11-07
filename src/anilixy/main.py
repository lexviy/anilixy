import logging

from anilixy.core.console import (
    enable_vt_output,
    open_in_own_window,
    set_window_title,
)

open_in_own_window()
set_window_title()
enable_vt_output()

from anilixy.app import AnilixyApp  # noqa: E402
from anilixy.core.discord_rpc import DiscordRPC  # noqa: E402
from anilixy.core.log import setup_logging  # noqa: E402
from anilixy.core.settings import load_discord  # noqa: E402

log = logging.getLogger(__name__)


def main() -> None:
    setup_logging()
    app = AnilixyApp()
    app.rpc = DiscordRPC()
    if load_discord():
        app.rpc.start()
    try:
        app.run()
    finally:
        rpc = getattr(app, "rpc", None)
        if rpc is not None:
            try:
                rpc.stop()
            except Exception:
                log.debug("ignored error", exc_info=True)


if __name__ == "__main__":
    main()
