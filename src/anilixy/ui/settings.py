from pathlib import Path

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import (
    Button,
    Input,
    OptionList,
    Select,
    Static,
    Switch,
)
from textual.widgets.option_list import Option

from anilixy.anilist.api import api_cache_stats, clear_api_cache
from anilixy.core import updater
from anilixy.core.settings import (
    QUALITIES,
    load_animation,
    load_autoplay_delay,
    load_discord,
    load_dub,
    load_ln_folder,
    load_notifications,
    load_quality,
    save_animation,
    save_autoplay_delay,
    save_discord,
    save_dub,
    save_ln_folder,
    save_notifications,
    save_quality,
    save_theme,
)
from anilixy.manga.offline import clear_downloads, downloads_stats
from anilixy.novels import library
from anilixy.ui.animations import KINDS, Backdrop
from anilixy.ui.covers import clear_cover_cache, cover_cache_stats, format_size
from anilixy.ui.dialogs import ConfirmScreen
from anilixy.ui.extensions import ExtensionsScreen
from anilixy.ui.extensions import summary as extensions_summary
from anilixy.ui.guide import GuideScreen
from anilixy.ui.sync import SyncScreen
from anilixy.ui.themes import THEMES
from anilixy.ui.widgets import FolderTree


class SettingsScreen(Screen):
    BINDINGS = [("escape", "app.pop_screen", "Back")]

    def compose(self) -> ComposeResult:
        yield Backdrop()
        with Vertical(id="settings-box"):
            with Horizontal(id="settings-header"):
                yield Static("Settings", id="settings-title", classes="box-title")
                yield Button("Help", id="open-guide", variant="primary")
            with Horizontal(id="version-row", classes="settings-row"):
                yield Static(f"Version {updater.current_version()}", id="version-info", classes="settings-label")
                yield Button("Update", id="update-app", variant="success")
            with Horizontal(id="cache-row"):
                yield Static("", id="cache-info")
                yield Button("Clean cache", id="clean-cache")
            with Horizontal(id="ln-row"):
                yield Static("Light novels folder", id="ln-label")
                yield Button("Change", id="ln-change")
            yield Static("", id="ln-info")
            with Horizontal(id="delay-row"):
                yield Static("Autoplay delay (seconds, 0 = none)", id="delay-label")
                yield Input(
                    value=str(load_autoplay_delay()),
                    type="integer",
                    id="delay-input",
                )
            with Horizontal(id="quality-row", classes="settings-row"):
                yield Static("Video quality (ani-cli)", classes="settings-label")
                yield Select(
                    [(q, q) for q in QUALITIES],
                    value=load_quality(),
                    allow_blank=False,
                    id="quality-select",
                )
            with Horizontal(id="dub-row", classes="settings-row"):
                yield Static("Dubbed version (ani-cli --dub)", classes="settings-label")
                yield Switch(value=load_dub(), id="dub-switch")
            with Horizontal(id="notify-row", classes="settings-row"):
                yield Static("Desktop notifications (new episodes/chapters)", classes="settings-label")
                yield Switch(value=load_notifications(), id="notify-switch")
            with Horizontal(id="discord-row"):
                yield Static("Discord Rich Presence", id="discord-label")
                yield Switch(value=load_discord(), id="discord-switch")
            with Horizontal(id="downloads-row", classes="settings-row"):
                yield Static("", id="downloads-info", classes="settings-label")
                yield Button("Clear downloads", id="clear-downloads")
            with Horizontal(id="extensions-row", classes="settings-row"):
                yield Static("", id="extensions-info", classes="settings-label")
                yield Button("Extensions", id="open-extensions")
            with Horizontal(id="sync-row", classes="settings-row"):
                yield Static("Sync progress with aniliphy (phone)", classes="settings-label")
                yield Button("Sync", id="open-sync")
            yield Static("Esc: back")

    def on_mount(self) -> None:
        self.update_cache_info()
        self.update_extensions_info()
        self.update_ln_info()
        self.check_version()

    def show_version(self, text) -> None:
        if self.is_attached:
            self.query_one("#version-info", Static).update(Text(text))

    @work(thread=True, exclusive=True, group="version")
    def check_version(self) -> None:
        current = updater.current_version()
        try:
            latest = updater.latest_release()
        except updater.UpdateError:
            return
        if updater.is_newer(latest["version"], current):
            text = f"Version {current} · {latest['version']} is out"
        else:
            text = f"Version {current} · the newest"
        self.app.call_from_thread(self.show_version, text)

    @work(thread=True, exclusive=True, group="version")
    def update_app(self) -> None:
        current = updater.current_version()
        try:
            latest = updater.latest_release()
            if not updater.is_newer(latest["version"], current):
                self.app.call_from_thread(self.show_version, f"Version {current} · the newest")
                self.app.call_from_thread(self.notify, "Already on the newest version")
                return
            if updater.frozen():
                import webbrowser

                webbrowser.open(latest["page"])
                self.app.call_from_thread(
                    self.notify,
                    f"Version {latest['version']} is out. Opened its page: download the new zip",
                )
                return
            self.app.call_from_thread(self.show_version, f"Version {current} · updating to {latest['version']}…")
            updater.install(latest)
        except updater.UpdateError as error:
            self.app.call_from_thread(self.show_version, f"Version {current}")
            self.app.call_from_thread(self.notify, str(error), severity="error")
            return
        finally:
            self.app.call_from_thread(self.enable_update_button)
        self.app.call_from_thread(self.updated, latest["version"])

    def enable_update_button(self) -> None:
        if self.is_attached:
            self.query_one("#update-app", Button).disabled = False

    def updated(self, version) -> None:
        self.show_version(f"Version {version} installed · restart to use it")
        self.app.push_screen(
            ConfirmScreen(f"Updated to {version}. Restart anilixy now?"),
            self.restart_confirmed,
        )

    def restart_confirmed(self, confirmed) -> None:
        if confirmed:
            self.app.exit("restart")

    def update_extensions_info(self) -> None:
        self.query_one("#extensions-info", Static).update(extensions_summary())

    def update_ln_info(self) -> None:
        folder = load_ln_folder()
        if folder.is_dir():
            count = len(library.list_books(folder))
            detail = f"{count} book{'s' if count != 1 else ''} found (EPUB/PDF)"
        else:
            detail = "Folder does not exist yet"
        self.query_one("#ln-info", Static).update(Text(f"{folder}\n{detail}"))

    def folder_chosen(self, result) -> None:
        if not result or not self.is_attached:
            return
        save_ln_folder(result)
        self.update_ln_info()
        self.notify(f"Light novels folder: {result}")

    def update_cache_info(self) -> None:
        count, size = cover_cache_stats()
        api_count, api_size = api_cache_stats()
        self.query_one("#cache-info", Static).update(
            f"Cover cache: {count} files · {format_size(size)}\n"
            f"AniList cache: {api_count} responses · {format_size(api_size)}"
        )
        chapters, used = downloads_stats()
        self.query_one("#downloads-info", Static).update(
            f"Offline manga: {chapters} chapter{'s' if chapters != 1 else ''} · {format_size(used)}"
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "clean-cache":
            count, size = clear_cover_cache()
            api_count, api_size = clear_api_cache()
            self.update_cache_info()
            self.notify(
                f"Cache cleaned: {count + api_count} files ({format_size(size + api_size)})"
            )
        elif event.button.id == "update-app":
            event.button.disabled = True
            self.show_version(f"Version {updater.current_version()} · looking for updates…")
            self.update_app()
        elif event.button.id == "open-extensions":
            self.app.push_screen(ExtensionsScreen(), lambda _: self.update_extensions_info())
        elif event.button.id == "open-sync":
            self.app.push_screen(SyncScreen())
        elif event.button.id == "open-guide":
            self.app.push_screen(GuideScreen())
        elif event.button.id == "clear-downloads":
            self.app.push_screen(
                ConfirmScreen("Delete all manga chapters saved offline?"),
                self.downloads_confirmed,
            )
        elif event.button.id == "ln-change":
            self.app.push_screen(
                FolderPickerScreen(load_ln_folder()), self.folder_chosen
            )

    def downloads_confirmed(self, confirmed) -> None:
        if confirmed:
            clear_downloads()
            self.update_cache_info()
            self.notify("Offline chapters deleted")

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "quality-select" and isinstance(event.value, str):
            save_quality(event.value)

    def on_switch_changed(self, event: Switch.Changed) -> None:
        if event.switch.id == "dub-switch":
            save_dub(event.value)
            return
        if event.switch.id == "notify-switch":
            save_notifications(event.value)
            return
        if event.switch.id != "discord-switch":
            return
        if event.value == load_discord():
            return
        save_discord(event.value)
        event.switch.disabled = True
        self.apply_discord(event.value)

    @work(thread=True)
    def apply_discord(self, enabled) -> None:
        rpc = getattr(self.app, "rpc", None)
        try:
            if rpc is None:
                return
            if enabled:
                if rpc.start():
                    self.app.call_from_thread(self.refresh_rpc)
                    self.app.call_from_thread(self.notify, "Discord Rich Presence on")
                else:
                    self.app.call_from_thread(
                        self.notify,
                        "Discord not found yet. Anilixy keeps trying in the background (is the client ID set?)",
                        severity="warning",
                    )
            else:
                rpc.stop()
                self.app.call_from_thread(self.notify, "Discord Rich Presence off")
        finally:
            self.app.call_from_thread(self.enable_discord_switch)

    def refresh_rpc(self) -> None:
        self.app._update_rpc(self.app.screen)

    def enable_discord_switch(self) -> None:
        if self.is_attached:
            self.query_one("#discord-switch", Switch).disabled = False

    def commit_delay(self, field) -> None:
        text = field.value.strip()
        if text.isdigit():
            save_autoplay_delay(int(text))
        field.value = str(load_autoplay_delay())

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "delay-input":
            self.commit_delay(event.input)

    def on_descendant_blur(self, event) -> None:
        if getattr(event.widget, "id", None) == "delay-input":
            self.commit_delay(event.widget)


class FolderPickerScreen(ModalScreen):
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, current) -> None:
        super().__init__()
        self.current = Path(current)

    def compose(self) -> ComposeResult:
        with Vertical(id="picker-box"):
            yield Static("Light novels folder", classes="box-title")
            yield Input(value=str(self.current), id="picker-path")
            yield FolderTree(Path.home(), id="picker-tree")
            yield Static(
                "Pick a folder or type a path (created if it does not exist)",
                id="picker-hint",
            )
            with Horizontal(id="picker-buttons"):
                yield Button("Select", id="picker-select", variant="success")
                yield Button("Cancel", id="picker-cancel")

    def on_directory_tree_directory_selected(self, event) -> None:
        event.stop()
        self.query_one("#picker-path", Input).value = str(event.path)

    def choose(self) -> None:
        text = self.query_one("#picker-path", Input).value.strip()
        if not text:
            self.notify("Type or pick a folder", severity="warning")
            return
        path = Path(text).expanduser()
        if not path.is_absolute():
            path = Path.home() / path
        if path.exists() and not path.is_dir():
            self.notify("That path is a file, not a folder", severity="error")
            return
        if not path.exists():
            try:
                path.mkdir(parents=True)
            except OSError as error:
                self.notify(f"Could not create the folder: {error}", severity="error")
                return
        self.dismiss(str(path))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "picker-select":
            self.choose()
        elif event.button.id == "picker-cancel":
            self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.choose()

    def action_cancel(self) -> None:
        self.dismiss(None)


class AnimationScreen(Screen):
    BINDINGS = [("escape", "cancel")]
    NAMES = {
        "off": "Off",
        "rain": "Rain",
        "snow": "Snow",
        "stars": "Falling stars",
        "sakura": "Sakura",
        "fireflies": "Fireflies",
        "waves": "Waves",
        "clouds": "Clouds",
        "lilies": "Spider lilies",
    }

    def __init__(self):
        super().__init__()
        self.original = load_animation()
        self.ready = False

    def compose(self) -> ComposeResult:
        yield Backdrop()
        with Vertical(id="anim-box"):
            yield Static("Change animation", classes="box-title")
            yield OptionList(
                *[Option(self.NAMES[kind], id=kind) for kind in KINDS], id="anim-list"
            )
            yield Static("Enter: confirm | Esc: cancel")

    def on_mount(self) -> None:
        anim_list = self.query_one("#anim-list", OptionList)
        if self.original in KINDS:
            anim_list.highlighted = KINDS.index(self.original)
        anim_list.focus()

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        if not self.ready:
            if event.option.id == self.original:
                self.ready = True
            return
        self.app.engine.set_kind(event.option.id)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        save_animation(event.option.id)
        self.app.engine.set_kind(event.option.id)
        self.notify(f"Animation: {self.NAMES[event.option.id]}")
        self.app.pop_screen()

    def action_cancel(self) -> None:
        self.app.engine.set_kind(self.original)
        self.app.pop_screen()


class ThemeScreen(Screen):
    BINDINGS = [("escape", "cancel")]

    def __init__(self):
        super().__init__()
        self.original = None
        self.ready = False

    def compose(self) -> ComposeResult:
        yield Backdrop()
        with Vertical(id="theme-box"):
            yield Static("Change theme", classes="box-title")
            yield OptionList(
                *[Option(t.name, id=t.name) for t in THEMES], id="theme-list"
            )
            yield Static("Enter: confirm | Esc: cancel")

    def on_mount(self) -> None:
        self.original = self.app.theme
        theme_list = self.query_one("#theme-list", OptionList)
        names = [t.name for t in THEMES]
        if self.original in names:
            theme_list.highlighted = names.index(self.original)
        theme_list.focus()

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        if not self.ready:
            if event.option.id == self.original:
                self.ready = True
            return
        self.app.theme = event.option.id

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.app.theme = event.option.id
        save_theme(event.option.id)
        self.notify(f"Theme: {event.option.id}")
        self.app.pop_screen()

    def action_cancel(self) -> None:
        self.app.theme = self.original
        self.app.pop_screen()
