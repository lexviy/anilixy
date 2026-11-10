import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import (
    Button,
    Static,
)
from textual_image.widget import Image

from anilixy.anilist.api import fetch_studio_page, toggle_favourite
from anilixy.anilist.formatting import anime_details, split_chunk
from anilixy.ui.animations import Backdrop
from anilixy.ui.covers import fit_cover, safe_cover
from anilixy.ui.widgets import ClickLabel

log = logging.getLogger(__name__)


CHUNK_SIZE = 20


class StudioScreen(Screen):
    BINDINGS = [("escape", "app.pop_screen", "Back")]

    def __init__(self, studio_id, studio_name):
        super().__init__()
        self.studio_id = studio_id
        self.studio_name = studio_name
        self.buffer = []
        self.next_page = 1
        self.has_next = True
        self.shown = 0
        self.loading = False
        self.cover_widgets = {}
        self.is_favourite = False
        self.favourite_loading = False

    def compose(self) -> ComposeResult:
        yield Backdrop()
        with Vertical(id="studio-box"):
            with Horizontal(id="studio-heading", classes="box-title"):
                yield Static(Text(self.studio_name), id="studio-name")
                yield ClickLabel(
                    "☆",
                    {"kind": "favourite"},
                    id="studio-favorite-star",
                    classes="clickable",
                )
            yield Static("Loading...", id="studio-count")
            yield VerticalScroll(
                Button("Load more", id="load-more", variant="primary"),
                id="studio-scroll",
            )
            yield Static("Click / Enter: open anime  |  Tab: move  |  Esc: back")

    def on_mount(self) -> None:
        self.query_one("#load-more", Button).display = False
        self.start_loading()

    def start_loading(self) -> None:
        self.loading = True
        button = self.query_one("#load-more", Button)
        button.label = "Loading..."
        button.disabled = True
        self.load_chunk()

    def fetch_next_page(self) -> None:
        data = fetch_studio_page(self.studio_id, self.next_page, self.app.token)
        self.buffer.extend(data["animes"])
        self.has_next = data["has_next"]
        self.is_favourite = data["is_favourite"]
        self.next_page += 1

    @work(thread=True)
    def load_chunk(self) -> None:
        try:
            while True:
                chunk, rest = split_chunk(self.buffer, CHUNK_SIZE)
                if rest or not self.has_next:
                    break
                self.fetch_next_page()
        except requests.RequestException:
            self.app.call_from_thread(
                self.notify, "Could not load studio", severity="error"
            )
            self.app.call_from_thread(self.loading_failed)
            return
        self.buffer = [a for _, items in rest for a in items]
        self.app.call_from_thread(self.set_favourite, self.is_favourite)
        self.app.call_from_thread(self.show_chunk, chunk)
        animes = [a for _, items in chunk for a in items]
        with ThreadPoolExecutor(max_workers=16) as pool:
            futures = {
                pool.submit(safe_cover, (a.get("coverImage") or {}).get("large")): a[
                    "id"
                ]
                for a in animes
            }
            for future in as_completed(futures):
                cover = future.result()
                if cover is not None:
                    self.app.call_from_thread(self.set_cover, futures[future], cover)

    def loading_failed(self) -> None:
        if not self.is_attached:
            return
        self.loading = False
        button = self.query_one("#load-more", Button)
        button.label = "Retry"
        button.disabled = False
        button.display = True
        self.query_one("#studio-count", Static).update("Failed to load")

    def build_row(self, a):
        title = a["title"]["english"] or a["title"]["romaji"] or "?"
        label = ClickLabel(
            title, {"kind": "media", "id": a["id"]}, classes="clickable studio-title"
        )
        picture = Image(classes="studio-cover")
        info = Vertical(
            label, Static(Text(anime_details(a), style="dim")), classes="studio-info"
        )
        return Horizontal(picture, info, classes="studio-row"), label, picture

    def show_chunk(self, chunk) -> None:
        if not self.is_attached:
            return
        scroll = self.query_one("#studio-scroll", VerticalScroll)
        button = self.query_one("#load-more", Button)
        widgets = []
        first_label = None
        for year, items in chunk:
            header = str(year) if year else "TBA"
            widgets.append(
                Static(Text(header, style="bold underline"), classes="year-header")
            )
            for a in items:
                row, label, picture = self.build_row(a)
                self.cover_widgets[a["id"]] = picture
                widgets.append(row)
                if first_label is None:
                    first_label = label
        if not widgets and self.shown == 0:
            widgets.append(Static("No titles"))
        if widgets:
            scroll.mount(*widgets, before=button)
        self.shown += sum(len(items) for _, items in chunk)
        more = bool(self.buffer) or self.has_next
        button.label = "Load more"
        button.disabled = False
        button.display = more
        self.loading = False
        count = f"{self.shown} titles"
        if more:
            count += " loaded"
        self.query_one("#studio-count", Static).update(count)
        if first_label is not None:
            self.call_after_refresh(self.focus_label, first_label)

    def set_cover(self, anime_id, cover) -> None:
        picture = self.cover_widgets.get(anime_id)
        if picture is not None and picture.is_attached:
            picture.image = fit_cover(cover, 10, 7)

    def focus_label(self, label) -> None:
        if label.is_attached:
            label.focus()

    def set_favourite(self, favourite) -> None:
        self.is_favourite = favourite
        try:
            star = self.query_one("#studio-favorite-star", ClickLabel)
            star.update(Text("★" if favourite else "☆", style="bold"))
            star.tooltip = (
                "Remove from favourites" if favourite else "Add to favourites"
            )
        except Exception:
            log.debug("ignored error", exc_info=True)

    def start_favourite_toggle(self) -> None:
        if self.favourite_loading:
            return
        if self.app.guest or not self.app.token:
            self.notify("Log in to add favourites", severity="warning")
            return
        self.favourite_loading = True
        self.change_favourite()

    @work(thread=True)
    def change_favourite(self) -> None:
        try:
            result = toggle_favourite(self.app.token, studio_id=self.studio_id)
        except Exception:
            self.app.call_from_thread(self.favourite_failed)
            return
        favourites = (result.get("studios") or {}).get("nodes") or []
        favourite = any(node.get("id") == self.studio_id for node in favourites)
        if not favourites:
            favourite = not self.is_favourite
        self.app.call_from_thread(self.favourite_changed, favourite)

    def favourite_changed(self, favourite) -> None:
        self.favourite_loading = False
        self.set_favourite(favourite)
        self.notify("Added to favourites" if favourite else "Removed from favourites")

    def favourite_failed(self) -> None:
        self.favourite_loading = False
        self.notify("Failed to update favourites", severity="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "load-more" and not self.loading:
            self.start_loading()

    def on_click_label_pressed(self, event: ClickLabel.Pressed) -> None:
        payload = event.label.payload
        if payload["kind"] == "favourite":
            self.start_favourite_toggle()
        elif payload["kind"] == "media":
            self.app.notify("Loading...", timeout=2)
            self.app.open_anime(payload["id"])
