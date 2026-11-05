import logging

from anilixy.app import AnilixyApp
from anilixy.core.discord_rpc import DiscordRPC
from anilixy.core.log import setup_logging
from anilixy.core.settings import load_discord

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
