import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, HorizontalScroll, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import (
    Button,
    Input,
    Static,
    TabbedContent,
    TabPane,
)
from textual_image.widget import Image

from anilixy.anilist.api import (
    RESTART_STATUSES,
    clean_description,
    fetch_details,
    fetch_progress,
    save_list_entry,
    start_media,
    toggle_favourite,
)
from anilixy.anilist.formatting import (
    manga_info_text,
    nice,
    recommendations_list,
    relations_list,
)
from anilixy.manga.history import (
    clear_last_chapter,
    forget_mapping,
    get_last_chapter,
    get_mapping,
    set_mapping,
)
from anilixy.manga.reader import MangaReaderScreen
from anilixy.manga.sources import (
    NO_SOURCES,
    make_source_id,
    manga_sources,
    missing_source,
    not_installed_message,
    openable,
    source_by_prefix,
    source_label,
)
from anilixy.novels.reading import reset_novel_progress
from anilixy.novels.screens import read_light_novel
from anilixy.ui.animations import Backdrop
from anilixy.ui.covers import fit_cover, safe_cover
from anilixy.ui.dialogs import SourcePickerScreen
from anilixy.ui.list_editor import ListEditorScreen
from anilixy.ui.people import CharacterScreen, StaffScreen
from anilixy.ui.picker import fzf_available, fzf_pick
from anilixy.ui.recommendations import RecommendationsMixin
from anilixy.ui.widgets import ClickLabel

log = logging.getLogger(__name__)


class MangaScreen(RecommendationsMixin, Screen):
    BINDINGS = [
        ("left", "app.focus_previous", "Previous"),
        ("right", "app.focus_next", "Next"),
        ("escape", "app.pop_screen", "Back"),
        ("1", "show_tab('tab-info')", "Information"),
        ("2", "show_tab('tab-staff')", "Staff"),
        ("3", "show_tab('tab-related')", "Related"),
        ("4", "show_tab('tab-recs')", "Recommendations"),
    ]

    STATUS_MAP = {
        "CURRENT": "Reading",
        "PLANNING": "Plan to read",
        "COMPLETED": "Completed",
        "DROPPED": "Dropped",
        "PAUSED": "On Hold",
        "REPEATING": "Rereading",
    }

    def __init__(self, manga):
        super().__init__()
        self.related_images = {}
        self.rec_images = {}
        self.anime = manga
        self._start_chapter = None
        self.user_info = None
        self.is_favourite = bool(manga.get("isFavourite"))
        self.favourite_loading = False

    def build_info_text(self) -> Text:
        a = self.anime

        vars = self.app.get_css_variables()
        primary = vars.get("primary", "cyan")
        secondary = vars.get("secondary", "magenta")
        accent = vars.get("accent", "yellow")
        fg = vars.get("foreground", "white")
        success = vars.get("success", "green")

        text = Text()

        text.append("Score: ", style=f"bold {accent}")
        text.append(f"{a.get('averageScore') or '?'}/100", style=fg)

        if self.user_info is not None:
            score = self.user_info.get("score")
            text.append("   ")
            text.append("|", style=f"bold {accent}")
            text.append("   Your score: ", style=f"bold {accent}")
            if score and score > 0:
                text.append(f"{score}/10", style=success)
            else:
                text.append("None", style="dim")
        text.append("\n")

        text.append("Chapters: ", style=f"bold {primary}")
        text.append(f"{a.get('chapters') or '?'}", style=fg)
        text.append("   ")
        text.append("|", style=f"bold {primary}")
        text.append("   Volumes: ", style=f"bold {primary}")
        text.append(f"{a.get('volumes') or '?'}", style=fg)

        if self.user_info is not None:
            status = self.user_info.get("status")
            text.append("   ")
            text.append("|", style=f"bold {primary}")
            text.append("   Status: ", style=f"bold {primary}")
            if status:
                text.append(f"{self.STATUS_MAP.get(status, status)}", style=success)
            else:
                text.append("None", style="dim")
        text.append("\n")

        fmt = a.get("format")
        if fmt:
            text.append("Format: ", style=f"bold {secondary}")
            text.append(f"{nice(fmt)}\n", style=fg)
        text.append("Genres: ", style=f"bold {secondary}")
        text.append(f"{', '.join(a.get('genres') or []) or '?'}", style=fg)
        return text

    def compose(self) -> ComposeResult:
        a = self.anime
        title = a["title"]["english"] or a["title"]["romaji"]
        yield Backdrop()
        with Vertical(id="anime-body"):
            with Horizontal(id="top"):
                with Vertical(id="left"):
                    with Horizontal(id="info"):
                        yield Static(self.build_info_text(), id="info-text")
                        yield ClickLabel(
                            "★" if self.is_favourite else "☆",
                            {"kind": "favourite"},
                            id="favorite-star",
                            classes="clickable",
                        )
                    with VerticalScroll(id="synopsis-box"):
                        yield Static(Text(title), id="title")
                        yield Static(
                            Text(clean_description(a.get("description"))), id="synopsis"
                        )
                yield Image(id="cover")
            with TabbedContent(id="middle"):
                with TabPane("Information", id="tab-info"):
                    with VerticalScroll():
                        yield Static("Loading...", id="info-body")
                with TabPane("Staff & Characters", id="tab-staff"):
                    with VerticalScroll():
                        yield Static("Loading...", id="staff-body")
                with TabPane("Related", id="tab-related"):
                    yield HorizontalScroll(
                        Static("Loading...", id="related-loading"), id="related-row"
                    )
                with TabPane("Recommendations", id="tab-recs"):
                    yield HorizontalScroll(
                        Static("Loading...", id="recs-loading"), id="recs-row"
                    )
            with Horizontal(id="bar"):
                yield Static("Chapter", id="episode-label")
                yield Input(value="", placeholder="auto", type="number", id="chapter")
                yield Button("Read", id="read", variant="success")
                if not self.app.guest:
                    yield Button("Add to list", id="add", variant="primary")
                yield Button("Source: auto", id="source")
                yield Button("Back", id="back")

    def on_mount(self) -> None:
        self.query_one("#read", Button).focus()
        if self.anime.get("format") == "NOVEL":
            self.query_one("#episode-label", Static).update("Start at AniList chapter")
            self.query_one("#chapter", Input).placeholder = "resume"
        self.update_source_label()
        self.load_main_cover()
        self.load_details()

    def update_source_label(self) -> None:
        button = self.query_one("#source", Button)
        if self.anime.get("format") == "NOVEL":
            button.display = False
            return
        label = source_label(get_mapping(self.anime["id"]))
        button.label = f"Source: {label}" if label else "Source: auto"

    @work(thread=True)
    def load_main_cover(self) -> None:
        images = self.anime.get("coverImage") or {}
        url = images.get("extraLarge") or images.get("large")
        cover = safe_cover(url)
        if cover is not None:
            self.app.call_from_thread(self.set_main_cover, cover)

    def set_main_cover(self, cover) -> None:
        if self.is_attached:
            self.query_one("#cover", Image).image = fit_cover(cover, 34, 24)

    @work(thread=True)
    def load_details(self) -> None:
        token = self.app.token
        try:
            details = fetch_details(self.anime["id"], token)
        except requests.RequestException:
            self.app.call_from_thread(self.load_failed)
            return
        user_info = None
        if token and not self.app.guest:
            try:
                user_info = fetch_progress(token, self.anime["id"])
            except requests.RequestException:
                user_info = None
        relations = relations_list(details)
        recs = recommendations_list(details)
        self.app.call_from_thread(
            self.fill_details, details, relations, user_info, recs
        )
        with ThreadPoolExecutor(max_workers=12) as pool:
            futures = {
                pool.submit(safe_cover, rel["cover_url"]): index
                for index, rel in enumerate(relations)
                if rel["cover_url"]
            }
            for future in as_completed(futures):
                cover = future.result()
                if cover is not None:
                    self.app.call_from_thread(
                        self.set_related_cover, futures[future], cover
                    )
        self.load_rec_covers(recs)

    def load_failed(self) -> None:
        if not self.is_attached:
            return
        self.notify("Failed to load details", severity="error")
        self.query_one("#info-body", Static).update("Failed to load")
        self.query_one("#staff-body", Static).update("Failed to load")
        self.query_one("#related-loading", Static).update("Failed to load")
        self.query_one("#recs-loading", Static).update("Failed to load")

    def fill_details(self, details, relations, user_info, recs) -> None:
        if not self.is_attached:
            return
        self.user_info = user_info
        self.set_default_chapter()
        self.query_one("#info-text", Static).update(self.build_info_text())
        self.set_favourite(bool(details.get("isFavourite")))
        self.query_one("#info-body", Static).update(
            manga_info_text(details, self.app.get_css_variables())
        )
        staff_box = self.query_one("#staff-body")
        staff_box.remove_children()
        staff_box.mount(Static(Text("Staff", style="bold underline")))
        for edge in (details.get("staff") or {}).get("edges") or []:
            person = edge.get("node") or {}
            staff_box.mount(
                ClickLabel(
                    (person.get("name") or {}).get("full") or "?",
                    {"kind": "staff", "id": person.get("id")},
                    classes="clickable",
                )
            )
            staff_box.mount(Static(Text(f"  {edge.get('role') or '?'}", style="dim")))
        staff_box.mount(Static(""))
        staff_box.mount(Static(Text("Characters", style="bold underline")))
        for edge in (details.get("characters") or {}).get("edges") or []:
            person = edge.get("node") or {}
            staff_box.mount(
                ClickLabel(
                    (person.get("name") or {}).get("full") or "?",
                    {"kind": "character", "id": person.get("id")},
                    classes="clickable",
                )
            )
            role = nice(edge.get("role"))
            voice_actors = edge.get("voiceActors") or []
            if voice_actors:
                voice_actor = (voice_actors[0].get("name") or {}).get("full") or "?"
                role += f"  CV: {voice_actor}"
            staff_box.mount(Static(Text(f"  {role}", style="dim")))
        self.fill_recommendations(recs)
        row = self.query_one("#related-row", HorizontalScroll)
        row.remove_children()
        self.related_images = {}
        if not relations:
            row.mount(Static("No related titles"))
            return
        for index, rel in enumerate(relations):
            payload = {"kind": "media", "id": rel["id"]}
            children = []
            if rel["cover_url"]:
                picture = Image(classes="rel-cover")
                self.related_images[index] = picture
                children.append(picture)
            children.append(
                ClickLabel(rel["title"], payload, classes="rel-title clickable")
            )
            children.append(Static(Text(rel["kind"]), classes="rel-kind"))
            row.mount(Vertical(*children, classes="rel-card"))

    def set_related_cover(self, index, cover) -> None:
        picture = self.related_images.get(index)
        if picture is not None and picture.is_attached:
            picture.image = fit_cover(cover, 12, 9)

    def set_favourite(self, favourite) -> None:
        self.is_favourite = favourite
        self.anime["isFavourite"] = favourite
        try:
            star = self.query_one("#favorite-star", ClickLabel)
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
            result = toggle_favourite(self.app.token, manga_id=self.anime["id"])
        except Exception:
            self.app.call_from_thread(self.favourite_failed)
            return
        favourites = (result.get("manga") or {}).get("nodes") or []
        if not favourites:
            favourites = (result.get("anime") or {}).get("nodes") or []
        favourite = any(node.get("id") == self.anime["id"] for node in favourites)
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
        elif payload["kind"] == "character":
            self.app.push_screen(CharacterScreen(payload["id"]))
        elif payload["kind"] == "staff":
            self.app.push_screen(StaffScreen(payload["id"]))

    def action_show_tab(self, tab_id: str) -> None:
        self.query_one(TabbedContent).active = tab_id

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "read":
            self.begin_reading()
        elif event.button.id == "add":
            self.app.push_screen(ListEditorScreen(self.anime, "MANGA"), self.list_saved)
        elif event.button.id == "source":
            self.app.push_screen(
                SourcePickerScreen(source_label(get_mapping(self.anime["id"]))),
                self.source_chosen,
            )
        elif event.button.id == "back":
            self.app.pop_screen()

    def list_saved(self, result) -> None:
        if not result or not self.is_attached:
            return
        self.user_info = {
            **(self.user_info or {}),
            "status": result["status"],
            "progress": result["progress"],
            "progressVolumes": result["progressVolumes"] or 0,
            "score": result["score"],
            "repeat": result["repeat"],
        }
        self.query_one("#info-text", Static).update(self.build_info_text())
        self.query_one("#chapter", Input).value = ""
        self.set_default_chapter()
        self.notify("List entry saved")

    def set_default_chapter(self) -> None:
        field = self.query_one("#chapter", Input)
        if field.value or self.anime.get("format") == "NOVEL":
            return
        info = self.user_info or {}
        status = info.get("status")
        progress = info.get("progress") or 0
        history = None
        last = get_last_chapter(self.anime["id"])
        if last:
            match = re.search(r"\d+(?:\.\d+)?", str(last.get("chapter_number") or ""))
            if match:
                history = float(match.group())
        if status == "COMPLETED" or (status in RESTART_STATUSES and not progress):
            value = "1"
        elif history is not None and progress <= history:
            value = f"{history:g}"
        elif progress:
            value = str(progress + 1)
        else:
            value = ""
        field.value = value

    def mark_current(self) -> None:
        if self.is_attached:
            self.user_info = {**(self.user_info or {}), "status": "CURRENT"}
            self.query_one("#info-text", Static).update(self.build_info_text())
        self.dispatch_read()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "chapter":
            self.begin_reading()

    def begin_reading(self) -> None:
        text = self.query_one("#chapter", Input).value.strip().replace(",", ".")
        if text:
            try:
                float(text)
            except ValueError:
                self.notify("Enter a valid chapter number", severity="warning")
                return
        self._start_chapter = text or None
        if self.app.guest or not self.app.token:
            self.dispatch_read()
            return
        self.query_one("#read", Button).disabled = True
        self.restart_then_read()

    @work(thread=True)
    def restart_then_read(self) -> None:
        media_id = self.anime["id"]
        info = self.user_info or {}
        progress = info.get("progress") or 0
        if info.get("status") in ("PLANNING", "PAUSED", "DROPPED") and progress > 0:
            try:
                save_list_entry(self.app.token, media_id, "CURRENT", progress)
            except Exception:
                self.app.call_from_thread(
                    self.notify, "Could not update your AniList status", severity="warning"
                )
                self.app.call_from_thread(self.dispatch_read)
            else:
                self.app.call_from_thread(self.mark_current)
            return
        status = None
        try:
            status = start_media(self.app.token, media_id)
        except Exception:
            self.app.call_from_thread(
                self.notify, "Could not update your AniList status", severity="warning"
            )
        if status:
            clear_last_chapter(media_id)
            reset_novel_progress(media_id)
        self.app.call_from_thread(self.dispatch_read, status)

    def dispatch_read(self, status=None) -> None:
        if not self.is_attached:
            return
        self.query_one("#read", Button).disabled = False
        if status:
            self.user_info = dict(self.user_info or {})
            self.user_info.update(
                {"status": status, "progress": 0, "progressVolumes": 0}
            )
            self.query_one("#info-text", Static).update(self.build_info_text())
            self.notify(
                f"AniList status: {self.STATUS_MAP.get(status, status)} (progress reset)"
            )
        if self.anime.get("format") == "NOVEL":
            self.start_reading_ln()
        else:
            self.start_reading()

    def start_reading(self) -> None:
        mapping = get_mapping(self.anime["id"])
        if openable(self.anime["id"], mapping):
            self.open_reader(mapping)
            return
        missing = missing_source(mapping)
        if missing:
            self.notify(not_installed_message(missing), severity="warning", timeout=6)
            return
        if not manga_sources():
            self.notify(NO_SOURCES, severity="warning", timeout=6)
            return
        self.notify("Searching sources...", timeout=2)
        self.find_source()

    def source_chosen(self, choice) -> None:
        if choice is None:
            return
        if choice == "forget":
            forget_mapping(self.anime["id"])
            self.update_source_label()
            self.notify("Saved source cleared, it will be searched again")
            return
        source = None if choice == "auto" else source_by_prefix(choice)
        if not manga_sources():
            self.notify(NO_SOURCES, severity="warning", timeout=6)
            return
        self.notify(f"Searching {source.name if source else 'sources'}...", timeout=2)
        self.find_source(source)

    def start_reading_ln(self) -> None:
        self.notify("Looking for the book...", timeout=2)
        self.find_ln_source()

    def _ln_start(self):
        try:
            return int(float(self._start_chapter)) if self._start_chapter else None
        except ValueError:
            return None

    @work(thread=True)
    def find_ln_source(self) -> None:
        read_light_novel(self.app, self.anime, start_chapter=self._ln_start())

    @work(thread=True)
    def find_source(self, only=None) -> None:
        title_data = self.anime.get("title") or {}
        titles = [
            t
            for t in (
                title_data.get("english"),
                title_data.get("romaji"),
                title_data.get("native"),
            )
            if t
        ]
        if not titles:
            self.app.call_from_thread(
                self.notify, "No title to search", severity="warning"
            )
            return
        sources = [only] if only else manga_sources()
        for position, source in enumerate(sources):
            results = []
            for t in titles:
                try:
                    results = source.search(t)
                except Exception:
                    log.warning("%s search failed for %r", source.name, t, exc_info=True)
                    results = []
                if results:
                    break
            if results:
                self.app.call_from_thread(self.pick_source, results, source)
                return
            if position + 1 < len(sources):
                following = sources[position + 1].name
                self.app.call_from_thread(
                    self.notify,
                    f"{source.name} found nothing. Trying {following}...",
                    timeout=2,
                )
        where = only.name if only else "any source"
        self.app.call_from_thread(
            self.notify, f"Not found in {where}.", severity="warning"
        )

    def pick_source(self, results, source) -> None:
        if not self.is_attached:
            return
        if fzf_available():
            series_url = fzf_pick(
                self.app,
                [(r["title"], r["url"]) for r in results],
                prompt=f"{source.name}> ",
            )
            if series_url is None:
                self.notify("Cancelled", severity="warning")
                return
        else:
            series_url = results[0]["url"]
        source_id = make_source_id(source, series_url)
        set_mapping(self.anime["id"], source_id)
        self.update_source_label()
        self.open_reader(source_id)

    def open_reader(self, source_id: str) -> None:
        if not self.is_attached:
            return
        a = self.anime
        title = a["title"]["english"] or a["title"]["romaji"] or ""
        self.app.push_screen(
            MangaReaderScreen(a["id"], source_id, title, start_chapter=self._start_chapter)
        )
