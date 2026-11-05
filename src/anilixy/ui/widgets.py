from rich.text import Text
from textual.containers import Horizontal
from textual.message import Message
from textual.widgets import (
    DirectoryTree,
    Static,
)


class AvatarRow(Horizontal):
    def on_resize(self, event) -> None:
        self.call_after_refresh(self.screen.fit_avatar)


class ClickLabel(Static):
    can_focus = True
    BINDINGS = [("enter", "press", "Open")]

    class Pressed(Message):
        def __init__(self, label: "ClickLabel") -> None:
            super().__init__()
            self.label = label

    def __init__(self, text: str, payload: dict, **kwargs) -> None:
        super().__init__(Text(text), **kwargs)
        self.payload = payload

    def on_click(self) -> None:
        self.post_message(self.Pressed(self))

    def action_press(self) -> None:
        self.post_message(self.Pressed(self))


class FolderTree(DirectoryTree):
    def filter_paths(self, paths):
        return [p for p in paths if p.is_dir() and not p.name.startswith(".")]
