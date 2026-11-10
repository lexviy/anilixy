import logging

from anilixy.core.console import (
    enable_vt_output,
    open_in_own_window,
    set_window_title,
)

open_in_own_window()
set_window_title()
enable_vt_output()

log = logging.getLogger(__name__)


def sync_on_quit() -> None:
    from anilixy.core import progress_sync

    settings = progress_sync.load_sync()
    if not settings["token"] or not settings["auto"]:
        return
    print("Syncing progress with aniliphy…", flush=True)
    try:
        progress_sync.sync()
    except Exception as error:
        log.warning("Sync on quitting failed: %s", error)


def main() -> None:
    from anilixy.app import AnilixyApp
    from anilixy.core.discord_rpc import DiscordRPC
    from anilixy.core.log import setup_logging
    from anilixy.core.settings import load_discord

    setup_logging()
    app = AnilixyApp()
    app.rpc = DiscordRPC()
    if load_discord():
        app.rpc.start()
    try:
        app.run()
    finally:
        sync_on_quit()
        rpc = getattr(app, "rpc", None)
        if rpc is not None:
            try:
                rpc.stop()
            except Exception:
                log.debug("ignored error", exc_info=True)
    if app.return_value == "restart":
        from anilixy.core import updater

        updater.restart()


if __name__ == "__main__":
    main()
