import requests
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import (
    Button,
    Input,
    OptionList,
    Static,
)
from textual.widgets.option_list import Option

from anilixy.anilist.login import (
    get_auth_url,
    load_client_id,
    logout,
    save_client_id,
    save_token,
)
from anilixy.anilist.profile import fetch_profile
from anilixy.anime.keep_watching import KeepWatchingScreen
from anilixy.core.browser import open_url
from anilixy.core.settings import save_guest
from anilixy.novels.screens import CustomNovelsScreen, KeepReadingScreen
from anilixy.ui.animations import Backdrop
from anilixy.ui.my_anilist import MyAniListScreen
from anilixy.ui.search import (
    CharacterSearchScreen,
    MangaSearchScreen,
    SearchScreen,
    StaffSearchScreen,
    StudioSearchScreen,
)
from anilixy.ui.settings import AnimationScreen, SettingsScreen, ThemeScreen

LOGO = """\
 █████╗ ███╗   ██╗██╗██╗     ██╗██╗  ██╗██╗   ██╗
██╔══██╗████╗  ██║██║██║     ██║╚██╗██╔╝╚██╗ ██╔╝
███████║██╔██╗ ██║██║██║     ██║ ╚███╔╝  ╚████╔╝ 
██╔══██║██║╚██╗██║██║██║     ██║ ██╔██╗   ╚██╔╝  
██║  ██║██║ ╚████║██║███████╗██║██╔╝ ██╗   ██║   
╚═╝  ╚═╝╚═╝  ╚═══╝╚═╝╚══════╝╚═╝╚═╝  ╚═╝   ╚═╝   """


DEV_URL = "https://anilist.co/settings/developer"


class LoginScreen(Screen):
    def compose(self) -> ComposeResult:
        yield Backdrop()
        with Vertical(id="login"):
            yield Static("Login AniList", classes="box-title")
            yield Static(
                "1. Create an app in [@click=screen.open_dev]anilist.co/settings/developer[/]"
            )
            yield Static("2. Paste the Client ID here:")
            yield Input(
                value=load_client_id() or "",
                placeholder="Client ID (Enter to open the link)",
                id="client-id",
            )
            yield Button("Token link (needs the id pasted above)", id="open-link")
            yield Static("3. Paste the token here:")
            yield Input(placeholder="Token", id="token")
            yield Button("Login", id="login-btn", variant="success")
            yield Button("Guest", id="guest")

    def open_in_browser(self, url: str) -> None:
        if not open_url(url):
            self.notify(url, title="Paste this link in your browser", timeout=15)

    def open_auth_link(self) -> None:
        client_id = self.query_one("#client-id", Input).value.strip()
        if not client_id:
            self.notify("Client ID missing", severity="warning")
            return
        save_client_id(client_id)
        self.open_in_browser(get_auth_url(client_id))

    def do_login(self) -> None:
        token = self.query_one("#token", Input).value.strip()
        if not token:
            self.notify("Token missing", severity="warning")
            return

        try:
            profile = fetch_profile(token)
        except requests.RequestException:
            self.notify("AniList error", severity="error")
            return

        if profile is None:
            self.notify("Invalid token", severity="error")
            return

        save_token(token)
        save_guest(False)
        self.app.token = token
        self.app.profile = profile
        self.app.start_update_checks()
        self.app.guest = False
        self.app.switch_screen(MenuScreen())

    def do_guest(self) -> None:
        save_guest(True)
        self.app.token = None
        self.app.profile = None
        self.app.guest = True
        self.app.switch_screen(MenuScreen())

    def action_open_dev(self) -> None:
        self.open_in_browser(DEV_URL)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "open-link":
            self.open_auth_link()
        elif event.button.id == "login-btn":
            self.do_login()
        elif event.button.id == "guest":
            self.do_guest()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "client-id":
            self.open_auth_link()
        elif event.input.id == "token":
            self.do_login()


class MenuScreen(Screen):
    def compose(self) -> ComposeResult:
        guest = self.app.guest
        profile = self.app.profile
        title = (
            "Guest mode"
            if guest
            else (f"Logged in as: {profile['name']}" if profile else "Anilixy")
        )

        options = [
            Option("Keep watching", id="keep"),
            Option("Keep reading", id="keep_manga"),
            Option("Search anime", id="search"),
            Option("Search manga/light novel", id="search_manga"),
            Option("Search character", id="search_char"),
            Option("Search staff", id="search_staff"),
            Option("Search studio", id="search_studio"),
            Option("Custom light novels", id="custom_ln"),
        ]
        if not guest:
            options.append(Option("My anilist", id="list"))
        options.append(Option("Change theme", id="theme"))
        options.append(Option("Change animation", id="animation"))
        options.append(Option("Settings", id="settings"))
        options.append(Option("Login" if guest else "Logout", id="logout"))
        options.append(Option("Exit", id="quit"))

        yield Backdrop()
        with Vertical(id="menu-wrap"):
            yield Static(LOGO, id="logo")
            with Vertical(id="menu"):
                yield Static(title, classes="box-title")
                yield OptionList(*options)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        choice = event.option.id
        if choice == "keep":
            self.app.push_screen(KeepWatchingScreen())
        elif choice == "keep_manga":
            self.app.push_screen(KeepReadingScreen())
        elif choice == "search":
            self.app.push_screen(SearchScreen())
        elif choice == "search_manga":
            self.app.push_screen(MangaSearchScreen())
        elif choice == "search_char":
            self.app.push_screen(CharacterSearchScreen())
        elif choice == "search_staff":
            self.app.push_screen(StaffSearchScreen())
        elif choice == "search_studio":
            self.app.push_screen(StudioSearchScreen())
        elif choice == "custom_ln":
            self.app.push_screen(CustomNovelsScreen())
        elif choice == "list":
            self.app.push_screen(MyAniListScreen())
        elif choice == "theme":
            self.app.push_screen(ThemeScreen())
        elif choice == "animation":
            self.app.push_screen(AnimationScreen())
        elif choice == "logout":
            if not self.app.guest:
                logout()
            save_guest(False)
            self.app.token = None
            self.app.profile = None
            self.app.guest = False
            self.app.switch_screen(LoginScreen())
        elif choice == "quit":
            self.app.exit()
        elif choice == "settings":
            self.app.push_screen(SettingsScreen())
