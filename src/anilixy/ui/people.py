import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, HorizontalScroll, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import (
    Static,
)
from textual_image.widget import Image

from anilixy.anilist.api import (
    clean_description,
    fetch_character,
    fetch_staff,
    toggle_favourite,
)
from anilixy.anilist.formatting import nice
from anilixy.ui.animations import Backdrop
from anilixy.ui.covers import fit_cover, safe_cover
from anilixy.ui.widgets import ClickLabel

log = logging.getLogger(__name__)


class CharacterScreen(Screen):
    BINDINGS = [("escape", "app.pop_screen", "Back")]
    person_kind = "character"

    def __init__(self, character_id):
        super().__init__()
        self.character_id = character_id
        self.related_images = {}
        self.is_favourite = False
        self.favourite_loading = False

    def compose(self) -> ComposeResult:
        yield Backdrop()
        with Vertical(id="char-body"):
            with Horizontal(id="char-top"):
                with Vertical(id="char-left"):
                    with Vertical(id="char-overview-box"):
                        yield Static("Overview", classes="char-section")
                        with VerticalScroll(id="char-desc-scroll"):
                            yield Static("Loading...", id="char-desc")
                    with Vertical(id="char-media-box"):
                        yield Static(
                            "Media", id="char-media-title", classes="char-section"
                        )
                        yield HorizontalScroll(
                            Static("Loading...", id="char-related-loading"),
                            id="char-related-row",
                        )
                with Vertical(id="char-right"):
                    with Vertical(id="char-image-box"):
                        with Horizontal(id="char-name-row", classes="char-section"):
                            yield Static("", id="char-name-box")
                            yield ClickLabel(
                                "☆",
                                {"kind": "favourite"},
                                id="person-favorite-star",
                                classes="clickable",
                            )
                        yield Image(id="char-image")
                    with Vertical(id="char-info-box"):
                        yield Static("Info", classes="char-section")
                        with VerticalScroll(id="char-info-scroll"):
                            yield Static("", id="char-info")

    def on_mount(self) -> None:
        self.load_character()

    def fetch_person(self):
        return fetch_character(self.character_id, self.app.token)

    @work(thread=True)
    def load_character(self) -> None:
        try:
            char = self.fetch_person()
        except Exception:
            self.app.call_from_thread(
                self.notify, f"Failed to load {self.person_kind}", severity="error"
            )
            return
        self.app.call_from_thread(self.fill_character, char)
        media_list = (char.get("media") or {}).get("edges") or []
        with ThreadPoolExecutor(max_workers=12) as pool:
            futures = {}
            for i, edge in enumerate(media_list):
                node = edge.get("node") or {}
                images = node.get("coverImage") or {}
                url = images.get("extraLarge") or images.get("large")
                if url:
                    futures[pool.submit(safe_cover, url)] = i
            for future in as_completed(futures):
                cover = future.result()
                if cover is not None:
                    self.app.call_from_thread(
                        self.set_char_related_cover, futures[future], cover
                    )

    def fill_character(self, char) -> None:
        if not self.is_attached:
            return
        name = (char.get("name") or {}).get("full") or "?"
        self.set_favourite(bool(char.get("isFavourite")))
        try:
            self.query_one("#char-name-box", Static).update(Text(name, style="bold"))
        except Exception:
            log.debug("ignored error", exc_info=True)
        try:
            self.query_one("#char-body").border_title = name
        except Exception:
            log.debug("ignored error", exc_info=True)
        raw_desc = char.get("description") or "No description."
        height_line = ""
        import re

        m = re.search(r"__Height:__\s*([^\n\r]+)", raw_desc)
        if m:
            height_line = m.group(1).strip()
            raw_desc = re.sub(r"__Height:__\s*[^\n\r]+\s*", "", raw_desc)
        if self.person_kind == "staff":
            description_lines = []
            for line in raw_desc.splitlines():
                without_links = re.sub(r"\[[^\]]+\]\([^)]+\)", "", line)
                if line.strip() and not without_links.strip(" |"):
                    continue
                description_lines.append(line)
            raw_desc = "\n".join(description_lines)
        desc = clean_description(raw_desc)
        desc = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", desc)
        desc = re.sub(r"\*\*([^*]+)\*\*", r"\1", desc)
        desc = re.sub(r"__([^_]+)__", r"\1", desc)
        desc = re.sub(r"\*([^*]+)\*", r"\1", desc)
        desc = re.sub(r"~~([^~]+)~~", r"\1", desc)
        try:
            self.query_one("#char-desc", Static).update(Text(desc))
        except Exception:
            log.debug("ignored error", exc_info=True)
        img_url = (char.get("image") or {}).get("large") or (
            char.get("image") or {}
        ).get("medium")
        if img_url:
            cover = safe_cover(img_url)
            if cover is not None:
                try:
                    self.query_one("#char-image", Image).image = fit_cover(
                        cover, 30, 24
                    )
                except Exception:
                    log.debug("ignored error", exc_info=True)
        info_lines = []
        age = char.get("age")
        gender = char.get("gender")
        blood = char.get("bloodType")
        dob = char.get("dateOfBirth") or {}
        if dob.get("day") and dob.get("month"):
            from anilixy.anilist.formatting import MONTHS

            bday = f"{MONTHS[dob['month'] - 1]} {dob['day']}"
            if dob.get("year"):
                bday += f", {dob['year']}"
            info_lines.append(f"Birthday: {bday}")
        if age:
            info_lines.append(f"Age: {age}")
        if gender:
            info_lines.append(f"Gender: {gender}")
        if blood:
            info_lines.append(f"Blood Type: {blood}")
        if height_line:
            info_lines.append(f"Height: {height_line}")
        occupations = char.get("primaryOccupations") or []
        if occupations:
            info_lines.append(f"Occupation: {', '.join(occupations)}")
        home_town = char.get("homeTown")
        if home_town:
            info_lines.append(f"Hometown: {home_town}")
        years_active = char.get("yearsActive") or []
        if years_active:
            start = years_active[0]
            end = years_active[1] if len(years_active) > 1 else None
            if start and end:
                active_text = f"{start}-{end}"
            elif start:
                active_text = f"{start}-present"
            else:
                active_text = str(end or "?")
            info_lines.append(f"Years active: {active_text}")
        name_data = char.get("name") or {}
        alts = name_data.get("alternative") or []
        alts_spoiler = name_data.get("alternativeSpoiler") or []
        if alts or alts_spoiler:
            info_lines.append("")
            info_lines.append("Also known as:")
            for a in alts:
                if a:
                    info_lines.append(f"- {a}")
            for a in alts_spoiler:
                if a:
                    info_lines.append(f"- {a} (spoiler)")
        try:
            self.query_one("#char-info", Static).update(
                Text("\n".join(info_lines), style="dim")
            )
        except Exception:
            log.debug("ignored error", exc_info=True)
        self.fill_char_related(char)

    def fill_char_related(self, char) -> None:
        if not self.is_attached:
            return
        row = self.query_one("#char-related-row", HorizontalScroll)
        row.remove_children()
        self.related_images = {}
        edges = ((char.get("media") or {}).get("edges")) or []
        self.query_one("#char-media-title", Static).update(f"Media · {len(edges)}")
        if not edges:
            row.mount(Static("Nothing found"))
            return
        for index, edge in enumerate(edges):
            node = edge.get("node") or {}
            role = edge.get("characterRole") or edge.get("staffRole") or ""
            title = (
                (node.get("title") or {}).get("english")
                or (node.get("title") or {}).get("romaji")
                or "?"
            )
            fmt = node.get("format") or ""
            media_type = node.get("type") or ""
            children = []
            picture = Image(classes="rel-cover")
            self.related_images[index] = picture
            children.append(picture)
            payload = {"kind": "media", "id": node.get("id")}
            children.append(ClickLabel(title, payload, classes="rel-title clickable"))
            if fmt == "NOVEL":
                kind_text = "Light novel"
            else:
                media_kind = {"ANIME": "Anime", "MANGA": "Manga"}.get(
                    media_type, nice(media_type)
                )
                format_name = fmt.replace("_", " ").title()
                if format_name.lower() == media_kind.lower():
                    format_name = ""
                kind_text = " · ".join(
                    part for part in (media_kind, format_name) if part
                ) or nice(role)
            children.append(Static(Text(kind_text), classes="rel-kind"))
            row.mount(Vertical(*children, classes="rel-card"))

    def set_char_related_cover(self, index, cover) -> None:
        picture = self.related_images.get(index)
        if picture is not None and picture.is_attached:
            picture.image = fit_cover(cover, 12, 9)

    def set_favourite(self, favourite) -> None:
        self.is_favourite = favourite
        try:
            star = self.query_one("#person-favorite-star", ClickLabel)
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
            result = toggle_favourite(
                self.app.token, **{f"{self.person_kind}_id": self.character_id}
            )
        except Exception:
            self.app.call_from_thread(self.favourite_failed)
            return
        connection = "characters" if self.person_kind == "character" else "staff"
        favourites = (result.get(connection) or {}).get("nodes") or []
        favourite = any(node.get("id") == self.character_id for node in favourites)
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

    def on_click_label_pressed(self, event: ClickLabel.Pressed) -> None:
        payload = event.label.payload
        if payload["kind"] == "favourite":
            self.start_favourite_toggle()
        elif payload["kind"] == "media":
            self.app.notify("Loading...", timeout=2)
            self.app.open_anime(payload["id"])


class StaffScreen(CharacterScreen):
    person_kind = "staff"

    def fetch_person(self):
        return fetch_staff(self.character_id, self.app.token)
