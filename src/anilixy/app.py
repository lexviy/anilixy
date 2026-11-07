import logging

import requests
from textual import work
from textual.app import App
from textual.screen import ModalScreen

from anilixy.anilist.api import fetch_media
from anilixy.anilist.login import load_token, logout
from anilixy.anilist.profile import fetch_profile
from anilixy.anime.screen import AnimeScreen
from anilixy.core import ipc
from anilixy.core.settings import load_animation, load_guest, load_theme
from anilixy.core.updates import check_updates, desktop_notify
from anilixy.manga.screen import MangaScreen
from anilixy.ui.animations import AnimationEngine
from anilixy.ui.dialogs import HelpScreen
from anilixy.ui.help_text import help_for
from anilixy.ui.menu import LoginScreen, MenuScreen
from anilixy.ui.themes import DEFAULT_THEME, THEMES

log = logging.getLogger(__name__)


class AnilixyApp(App):
    CSS_PATH = "anilixy.tcss"

    BINDINGS = [("ctrl+q", "quit"), ("question_mark", "show_help", "Help")]

    def __init__(self):
        super().__init__()
        self.token = load_token()
        self.profile = None
        self.guest = False
        self.engine = AnimationEngine(self)

    def on_mount(self) -> None:
        self.screen_change_signal.subscribe(self, self._update_rpc)
        for theme in THEMES:
            self.register_theme(theme)
        saved = load_theme()
        valid = {t.name for t in THEMES}
        self.theme = saved if saved in valid else DEFAULT_THEME
        self.engine.start(load_animation())
        if ipc.WINDOWS:
            self._sync_available = True
        if not self.token:
            if load_guest():
                self.guest = True
                self.push_screen(MenuScreen())
            else:
                self.push_screen(LoginScreen())
            return
        try:
            self.profile = fetch_profile(self.token)
        except requests.RequestException:
            self.notify("AniList error", severity="warning")
            self.push_screen(MenuScreen())
            return
        if self.profile is None:
            logout()
            self.token = None
            self.notify("Session expired, please login again", severity="warning")
            self.push_screen(LoginScreen())
        else:
            self.push_screen(MenuScreen())
            self.start_update_checks()

    UPDATE_INTERVAL = 30 * 60

    def start_update_checks(self) -> None:
        self.set_timer(10, self.check_updates)
        self.set_interval(self.UPDATE_INTERVAL, self.check_updates)

    @work(thread=True, exclusive=True, group="updates")
    def check_updates(self) -> None:
        if self.guest or not self.token or not self.profile:
            return
        try:
            messages = check_updates(self.token, self.profile["id"])
        except Exception:
            log.warning("Update check failed", exc_info=True)
            return
        for title, body in messages:
            desktop_notify(title, body)
            self.call_from_thread(self.notify, body, title=title, timeout=8)

    def action_show_help(self) -> None:
        screen = self.screen
        if isinstance(screen, ModalScreen):
            return
        found = help_for(screen)
        if found is None:
            return
        title, rows = found
        opening = getattr(screen, "help_opening", None)
        if opening is not None:
            opening()

        def closed(_result) -> None:
            done = getattr(screen, "help_closed", None)
            if done is not None:
                done()

        self.push_screen(HelpScreen(title, rows), closed)

    def _update_rpc(self, screen) -> None:
        rpc = getattr(self, "rpc", None)
        if rpc is None:
            return
        profile = self.profile or {}
        avatar = profile.get("avatar") or {}
        rpc.avatar = avatar.get("large") or avatar.get("medium")
        rpc.user = profile.get("name")
        if type(screen).__name__ in ("MangaReaderScreen", "LightNovelReaderScreen"):
            try:
                rpc.reading(screen.anilist_id, screen.title, screen.rpc_progress())
            except Exception:
                log.debug("ignored error", exc_info=True)
            return
        anime = getattr(screen, "anime", None)
        if anime is None:
            anime = getattr(screen, "character", None)
        if anime is None:
            anime = getattr(screen, "studio", None)
        try:
            rpc.browsing(type(screen).__name__, anime)
        except Exception:
            log.debug("ignored error", exc_info=True)

    @work(thread=True)
    def open_anime(self, media_id: int) -> None:
        try:
            anime = fetch_media(media_id)
        except requests.RequestException:
            self.call_from_thread(
                self.notify, "Could not load that media", severity="error"
            )
            return
        self.call_from_thread(self.show_anime, anime)

    def show_anime(self, anime) -> None:
        mtype = anime.get("type") if isinstance(anime, dict) else None
        if mtype == "MANGA":
            self.push_screen(MangaScreen(anime))
        else:
            self.push_screen(AnimeScreen(anime))
