from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, OptionList, Static
from textual.widgets.option_list import Option


class HelpScreen(ModalScreen):
    BINDINGS = [
        ("escape", "close", "Close"),
        ("question_mark", "close", "Close"),
        ("q", "close", "Close"),
    ]

    def __init__(self, title, rows) -> None:
        super().__init__()
        self.title_text = title
        self.rows = rows

    def compose(self) -> ComposeResult:
        text = Text()
        for key, description in self.rows:
            if not key and not description:
                text.append("\n")
            elif not description:
                text.append(f"{key}\n", style="bold underline")
            else:
                text.append(f"{key:<22}", style="bold")
                text.append(f"{description}\n")
        with Vertical(id="help-box"):
            yield Static(Text(f"Keys: {self.title_text}"), classes="box-title")
            with VerticalScroll(id="help-scroll"):
                yield Static(text)
            yield Static("Esc or ?: close")

    def action_close(self) -> None:
        self.dismiss(None)


class ConfirmScreen(ModalScreen):
    BINDINGS = [
        ("y", "yes", "Yes"),
        ("n", "no", "No"),
        ("escape", "no", "No"),
    ]

    def __init__(self, message, detail="") -> None:
        super().__init__()
        self.message = message
        self.detail = detail

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-box"):
            yield Static(Text(self.message), classes="box-title")
            if self.detail:
                yield Static(Text(self.detail, style="dim"))
            with Horizontal(id="confirm-buttons"):
                yield Button("Yes (Y)", id="confirm-yes", variant="error")
                yield Button("No (N)", id="confirm-no", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#confirm-no", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm-yes")

    def action_yes(self) -> None:
        self.dismiss(True)

    def action_no(self) -> None:
        self.dismiss(False)


class SourcePickerScreen(ModalScreen):
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, current=None) -> None:
        super().__init__()
        self.current = current

    def compose(self) -> ComposeResult:
        from anilixy.manga.sources import MANGA_SOURCES

        current = self.current.name if self.current else "none (auto)"
        with Vertical(id="source-box"):
            yield Static("Manga source", classes="box-title")
            yield Static(
                f"Current: {current}. Pick where to search; the chosen series is saved.",
                id="source-hint",
            )
            order = " → ".join(source.name for source in MANGA_SOURCES)
            options = [Option(f"Auto ({order})", id="auto")]
            options += [
                Option(f"Search on {source.name}", id=source.prefix)
                for source in MANGA_SOURCES
            ]
            options.append(Option("Forget the saved source", id="forget"))
            yield OptionList(*options, id="source-list")
            with Horizontal(id="source-buttons"):
                yield Button("Cancel", id="source-cancel")

    def on_mount(self) -> None:
        self.query_one("#source-list", OptionList).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option.id)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "source-cancel":
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)
