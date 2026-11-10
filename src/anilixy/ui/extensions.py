import os
import subprocess
import sys

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from anilixy.core import extensions
from anilixy.core.browser import open_url

EXPLAIN = (
    "Manga chapters and light novel volumes come from sources, which come from "
    "extensions: Python files or folders you put in the folder below. anilixy "
    "doesn't come with any. Anime is played by ani-cli and needs none."
)


def summary() -> str:
    found = extensions.installed()
    sources = len(extensions.manga_sources()) + len(extensions.novel_sources())
    if not found:
        return "Extensions: none installed"
    broken = sum(1 for extension in found if extension.problem)
    text = f"Extensions: {len(found)} installed, {sources} source{'s' if sources != 1 else ''}"
    return text + (f" · {broken} with a problem" if broken else "")


def describe() -> Text:
    text = Text()
    text.append("Folder: ", style="bold")
    text.append(f"{extensions.extensions_dir()}\n\n")
    text.append("Installed\n", style="bold")
    found = extensions.installed()
    if not found:
        text.append("  No extension is installed.\n")
    for extension in found:
        text.append(f"  {extension.name}")
        if extension.sources:
            text.append(f" · {', '.join(extension.sources)}")
        text.append("\n")
        if extension.problem:
            text.append(f"    {extension.problem}\n", style="red")
    text.append("\nSources\n", style="bold")
    for kind, sources in (
        ("Manga", extensions.manga_sources()),
        ("Light novels", extensions.novel_sources()),
    ):
        names = ", ".join(source.name for source in sources) or "none installed"
        text.append(f"  {kind}: {names}\n")
    return text


def open_folder(folder) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        os.startfile(folder)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(folder)], start_new_session=True)
    else:
        open_url(str(folder))


class ExtensionsScreen(ModalScreen):
    BINDINGS = [("escape", "close", "Close")]

    def compose(self) -> ComposeResult:
        with Vertical(id="extensions-box"):
            yield Static("Extensions", classes="box-title")
            yield Static(Text(EXPLAIN), id="extensions-hint")
            yield Static(describe(), id="extensions-list")
            with Horizontal(id="extensions-buttons"):
                yield Button("Open folder", id="extensions-folder")
                yield Button("Reload", id="extensions-reload", variant="primary")
                yield Button("Close", id="extensions-close")
            yield Static("Esc: close")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "extensions-folder":
            try:
                open_folder(extensions.extensions_dir())
            except OSError as error:
                self.notify(f"Could not open the folder: {error}", severity="error")
        elif event.button.id == "extensions-reload":
            extensions.reload()
            self.query_one("#extensions-list", Static).update(describe())
            self.notify(summary(), timeout=3)
        elif event.button.id == "extensions-close":
            self.dismiss()

    def action_close(self) -> None:
        self.dismiss()
