import time
import webbrowser

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static, Switch

from anilixy.core import progress_sync
from anilixy.ui.dialogs import ConfirmScreen

EXPLAIN = (
    "Keeps where you stopped the same here and in aniliphy on the phone: the episode and its "
    "minute, the manga chapter and page, the light novel chapter and the sources picked. "
    "AniList progress already goes through AniList. Both apps keep it in a private gist "
    "on your GitHub account.\n\n"
    "Make a token with only the gist permission and paste it here and on the phone. "
    "The same token finds the same gist."
)


def last_line(settings) -> str:
    last = settings.get("last")
    if not last:
        return "Never synced"
    minutes = int((time.time() - last) // 60)
    if minutes < 1:
        return "Last synced just now"
    if minutes < 60:
        return f"Last synced {minutes} min ago"
    if minutes < 48 * 60:
        return f"Last synced {minutes // 60} h ago"
    return "Last synced " + time.strftime("%d %b %Y", time.localtime(last))


class SyncScreen(ModalScreen):
    BINDINGS = [("escape", "close", "Close")]

    def compose(self) -> ComposeResult:
        settings = progress_sync.load_sync()
        with Vertical(id="sync-box"):
            yield Static("Sync with aniliphy", classes="box-title")
            yield Static(Text(EXPLAIN), id="sync-hint")
            yield Input(
                value=settings["token"],
                password=True,
                placeholder="GitHub token (ghp_…)",
                id="sync-token",
            )
            with Horizontal(classes="settings-row"):
                yield Static("Sync on opening and quitting", classes="settings-label")
                yield Switch(value=settings["auto"], id="sync-auto")
            yield Static(last_line(settings), id="sync-status")
            with Horizontal(id="sync-buttons"):
                yield Button("Make a token", id="sync-new-token")
                yield Button("Forget", id="sync-forget", variant="error")
                yield Button("Sync now", id="sync-now", variant="success")
            yield Static("Esc: close")

    def on_mount(self) -> None:
        self.query_one("#sync-forget", Button).display = bool(progress_sync.load_sync()["token"])

    def show(self, text) -> None:
        if self.is_attached:
            self.query_one("#sync-status", Static).update(Text(text))

    def start(self) -> None:
        token = self.query_one("#sync-token", Input).value.strip()
        if not token:
            self.show("Paste a token first")
            return
        if token != progress_sync.load_sync()["token"]:
            progress_sync.save_sync(token=token, gist="")
        self.query_one("#sync-now", Button).disabled = True
        self.show("Syncing…")
        self.run_sync(token)

    @work(thread=True, exclusive=True, group="sync")
    def run_sync(self, token) -> None:
        try:
            said = progress_sync.sync(token)
        except progress_sync.SyncError as error:
            said = str(error)
        except Exception:
            progress_sync.log.warning("Sync failed", exc_info=True)
            said = "Sync failed"
        self.app.call_from_thread(self.finished, said)

    def finished(self, said) -> None:
        if not self.is_attached:
            return
        self.query_one("#sync-now", Button).disabled = False
        settings = progress_sync.load_sync()
        self.query_one("#sync-forget", Button).display = bool(settings["token"])
        self.show(f"{said} · {last_line(settings)}")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "sync-token":
            self.start()

    def on_switch_changed(self, event: Switch.Changed) -> None:
        if event.switch.id == "sync-auto":
            progress_sync.save_sync(auto=event.value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "sync-now":
            self.start()
        elif event.button.id == "sync-new-token":
            webbrowser.open(progress_sync.NEW_TOKEN_URL)
            self.show("Opened GitHub. Make the token, copy it and paste it above")
        elif event.button.id == "sync-forget":
            self.app.push_screen(
                ConfirmScreen(
                    "Forget the token?",
                    "This computer stops syncing. Your progress here and the gist on GitHub stay as they are.",
                ),
                self.forget_confirmed,
            )

    def forget_confirmed(self, confirmed) -> None:
        if not confirmed:
            return
        progress_sync.forget_sync()
        self.query_one("#sync-token", Input).value = ""
        self.query_one("#sync-forget", Button).display = False
        self.show("Token forgotten")

    def action_close(self) -> None:
        self.dismiss(None)
