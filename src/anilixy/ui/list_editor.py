import requests
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Input,
    Static,
)

from anilixy.anilist.api import fetch_progress, save_list_entry


class ListEditorScreen(ModalScreen):
    BINDINGS = [("escape", "cancel", "Cancel")]

    STATUS_ORDER = [
        "CURRENT",
        "PLANNING",
        "COMPLETED",
        "DROPPED",
        "PAUSED",
        "REPEATING",
    ]
    ANIME_LABELS = {
        "CURRENT": "Watching",
        "PLANNING": "Planning",
        "COMPLETED": "Completed",
        "DROPPED": "Dropped",
        "PAUSED": "Paused",
        "REPEATING": "Rewatching",
    }
    MANGA_LABELS = {
        "CURRENT": "Reading",
        "PLANNING": "Planning",
        "COMPLETED": "Completed",
        "DROPPED": "Dropped",
        "PAUSED": "Paused",
        "REPEATING": "Rereading",
    }

    def __init__(self, media, kind) -> None:
        super().__init__()
        self.media = media
        self.is_anime = kind == "ANIME"
        self.labels = self.ANIME_LABELS if self.is_anime else self.MANGA_LABELS
        self.status = "PLANNING"
        self.progress_total = media.get("episodes" if self.is_anime else "chapters")
        self.volumes_total = None if self.is_anime else media.get("volumes")
        self.original_volumes = 0
        self.loaded = False
        self.saving = False

    def field(self, label, input_id, total=None, input_type="integer"):
        children = [
            Static(label, classes="editor-label"),
            Input(value="", type=input_type, id=input_id),
        ]
        if total is not None:
            children.append(Static(total, classes="editor-total"))
        return Horizontal(*children, classes="editor-cell")

    def compose(self) -> ComposeResult:
        titles = self.media.get("title") or {}
        title = titles.get("english") or titles.get("romaji") or "?"
        fields = [
            self.field(
                "Episodes" if self.is_anime else "Chapters",
                "editor-progress",
                f"/ {self.progress_total or '?'}",
            )
        ]
        if not self.is_anime:
            fields.append(
                self.field(
                    "Volumes", "editor-volumes", f"/ {self.volumes_total or '?'}"
                )
            )
        fields.append(self.field("Rating", "editor-score", "/ 10", "number"))
        fields.append(self.field("Repeat", "editor-repeat"))

        with VerticalScroll(id="editor-box"):
            yield Static("Add to list", classes="box-title")
            yield Static(Text(title), id="editor-title")
            for chunk in (self.STATUS_ORDER[:3], self.STATUS_ORDER[3:]):
                with Horizontal(classes="editor-status-row"):
                    for status in chunk:
                        yield Button(self.labels[status], id=f"status-{status}")
            for index in range(0, len(fields), 2):
                with Horizontal(classes="editor-field-row"):
                    yield from fields[index : index + 2]
            with Horizontal(id="editor-buttons"):
                yield Button("Save", id="editor-save", variant="success", disabled=True)
                yield Button("Cancel", id="editor-cancel")

    def on_mount(self) -> None:
        self.select_status(self.status)
        self.load_entry()

    @work(thread=True)
    def load_entry(self) -> None:
        info = None
        try:
            info = fetch_progress(self.app.token, self.media["id"])
        except requests.RequestException:
            self.app.call_from_thread(
                self.notify, "Could not load your current entry", severity="warning"
            )
        self.app.call_from_thread(self.fill, info)

    def fill(self, info) -> None:
        if not self.is_attached:
            return
        info = info or {}
        self.original_volumes = info.get("progressVolumes") or 0
        self.query_one("#editor-progress", Input).value = str(info.get("progress") or 0)
        if not self.is_anime:
            self.query_one("#editor-volumes", Input).value = str(self.original_volumes)
        score = info.get("score") or 0
        self.query_one("#editor-score", Input).value = f"{score:g}" if score else ""
        self.query_one("#editor-repeat", Input).value = str(info.get("repeat") or 0)
        self.select_status(info.get("status") or "PLANNING")
        self.loaded = True
        self.query_one("#editor-save", Button).disabled = False

    def select_status(self, status, fill_max=False) -> None:
        self.status = status
        for name in self.STATUS_ORDER:
            self.query_one(f"#status-{name}", Button).variant = (
                "primary" if name == status else "default"
            )
        if status != "COMPLETED" or not fill_max:
            return
        if self.progress_total:
            self.query_one("#editor-progress", Input).value = str(self.progress_total)
        else:
            self.notify("Total unknown, set it manually", severity="warning")
        if not self.is_anime and self.volumes_total:
            self.query_one("#editor-volumes", Input).value = str(self.volumes_total)

    def read_int(self, selector, maximum) -> int:
        try:
            value = max(0, int(self.query_one(selector, Input).value.strip()))
        except ValueError:
            value = 0
        return min(value, maximum) if maximum else value

    def read_score(self) -> float:
        text = self.query_one("#editor-score", Input).value.strip().replace(",", ".")
        try:
            value = float(text)
        except ValueError:
            value = 0.0
        return round(min(10.0, max(0.0, value)), 1)

    def collect(self) -> dict:
        return {
            "status": self.status,
            "progress": self.read_int("#editor-progress", self.progress_total),
            "progressVolumes": (
                None
                if self.is_anime
                else self.read_int("#editor-volumes", self.volumes_total)
            ),
            "score": self.read_score(),
            "repeat": self.read_int("#editor-repeat", None),
        }

    def start_save(self) -> None:
        if self.saving or not self.loaded:
            return
        self.saving = True
        self.query_one("#editor-save", Button).disabled = True
        self.save_entry(self.collect())

    @work(thread=True)
    def save_entry(self, values) -> None:
        volumes = values["progressVolumes"]
        if volumes is not None and volumes == 0 and self.original_volumes == 0:
            volumes = None
        try:
            save_list_entry(
                self.app.token,
                self.media["id"],
                values["status"],
                values["progress"],
                volumes,
                values["score"],
                values["repeat"],
            )
        except Exception as error:
            self.app.call_from_thread(self.save_failed, str(error))
            return
        self.app.call_from_thread(self.dismiss, values)

    def save_failed(self, message) -> None:
        self.saving = False
        if self.is_attached:
            self.query_one("#editor-save", Button).disabled = False
        self.notify(f"Failed to save: {message}", severity="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id.startswith("status-"):
            self.select_status(button_id[len("status-") :], fill_max=True)
        elif button_id == "editor-save":
            self.start_save()
        elif button_id == "editor-cancel":
            self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.start_save()

    def action_cancel(self) -> None:
        self.dismiss(None)
