import logging
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
    toggle_favourite,
)
from anilixy.anilist.formatting import (
    info_text,
    nice,
    recommendations_list,
    relations_list,
    split_studios,
)
from anilixy.anime.entries import forget_entry
from anilixy.anime.progress import get_local_progress
from anilixy.anime.resume import format_time, load_resume
from anilixy.anime.watching import watch
from anilixy.ui.animations import Backdrop
from anilixy.ui.covers import fit_cover, safe_cover
from anilixy.ui.list_editor import ListEditorScreen
from anilixy.ui.people import CharacterScreen, StaffScreen
from anilixy.ui.recommendations import RecommendationsMixin
from anilixy.ui.studio import StudioScreen
from anilixy.ui.widgets import ClickLabel

log = logging.getLogger(__name__)


class AnimeScreen(RecommendationsMixin, Screen):
    BINDINGS = [
        ("left", "app.focus_previous", "Previous"),
        ("right", "app.focus_next", "Next"),
        ("escape", "app.pop_screen", "Back"),
        ("1", "show_tab('tab-info')", "Information"),
        ("2", "show_tab('tab-staff')", "Staff"),
        ("3", "show_tab('tab-related')", "Related"),
        ("4", "show_tab('tab-recs')", "Recommendations"),
    ]

    def __init__(self, anime):
        super().__init__()
        self.related_images = {}
        self.rec_images = {}
        self.anime = anime
        self.user_info = None
        self.is_favourite = bool(anime.get("isFavourite"))
        self.favourite_loading = False

    def compose(self) -> ComposeResult:
        a = self.anime
        title = a["title"]["english"] or a["title"]["romaji"]

        vars = self.app.get_css_variables()
        primary = vars.get("primary", "cyan")
        secondary = vars.get("secondary", "magenta")
        accent = vars.get("accent", "yellow")
        fg = vars.get("foreground", "white")

        info = Text()
        info.append("Score: ", style=f"bold {accent}")
        info.append(f"{a['averageScore'] or '?'}/100\n", style=fg)
        info.append("Episodes: ", style=f"bold {primary}")
        info.append(f"{a['episodes'] or '?'}\n", style=fg)
        info.append("Genres: ", style=f"bold {secondary}")
        info.append(f"{', '.join(a['genres']) or '?'}", style=fg)

        yield Backdrop()

        with Vertical(id="anime-body"):
            with Horizontal(id="top"):
                with Vertical(id="left"):
                    with Horizontal(id="info"):
                        yield Static(info, id="info-text")
                        yield ClickLabel(
                            "★" if self.is_favourite else "☆",
                            {"kind": "favourite"},
                            id="favorite-star",
                            classes="clickable",
                        )
                    with VerticalScroll(id="synopsis-box"):
                        yield Static(Text(title), id="title")
                        yield Static(
                            Text(clean_description(a["description"])), id="synopsis"
                        )
                yield Image(id="cover")

            with TabbedContent(id="middle"):
                with TabPane("Information", id="tab-info"):
                    with VerticalScroll():
                        yield Static("Loading...", id="info-body")
                        yield Vertical(id="studios-box")
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
                yield Static("Episode", id="episode-label")
                yield Input(value="", placeholder="auto", type="integer", id="episode")
                yield Button("Watch", id="watch", variant="success")
                if not self.app.guest:
                    yield Button("Add to list", id="add", variant="primary")
                yield Button("Reset source", id="reset")
                yield Button("Back", id="back")

    auto_episode = None

    def on_mount(self) -> None:
        self.query_one("#watch", Button).focus()
        self.load_main_cover()
        self.load_details()
        self.load_progress()

    @work(thread=True)
    def load_progress(self) -> None:
        resume = load_resume(self.anime["id"])
        if self.app.guest:
            info = {
                "progress": get_local_progress(self.anime["id"]),
                "episodes": self.anime["episodes"],
            }
        else:
            try:
                info = fetch_progress(self.app.token, self.anime["id"])
            except requests.RequestException:
                info = None
        if not self.app.guest and info is not None:
            self.user_info = info
            self.app.call_from_thread(self.update_user_info)
        restart = info is not None and (
            info.get("status") == "COMPLETED"
            or (info.get("status") in RESTART_STATUSES and not info.get("progress"))
        )
        if info is not None:
            episode = 1 if restart else (info.get("progress") or 0) + 1
            total = info["episodes"]
            if total and episode > total:
                episode = 1
        else:
            episode = None
        place = None
        if (
            not restart
            and resume
            and (info is None or resume["episode"] > info["progress"])
        ):
            episode = resume["episode"]
            place = resume["position"]
        if episode is not None:
            self.app.call_from_thread(self.set_episode, episode, place)

    def update_user_info(self) -> None:
        if not self.is_attached:
            return
        info = self.user_info
        if not info:
            return
        status = info.get("status")
        score = info.get("score")
        status_map = {
            "CURRENT": "Watching",
            "PLANNING": "Plan to watch",
            "COMPLETED": "Completed",
            "DROPPED": "Dropped",
            "PAUSED": "On Hold",
            "REPEATING": "Rewatching",
        }
        a = self.anime
        avg = a.get("averageScore") or "?"

        vars = self.app.get_css_variables()
        primary = vars.get("primary", "cyan")
        secondary = vars.get("secondary", "magenta")
        accent = vars.get("accent", "yellow")
        fg = vars.get("foreground", "white")
        success = vars.get("success", "green")

        info_text_widget = Text()

        info_text_widget.append("Score: ", style=f"bold {accent}")
        info_text_widget.append(f"{avg}/100", style=fg)
        info_text_widget.append("   ")
        info_text_widget.append("|", style=f"bold {accent}")
        info_text_widget.append("   Your score: ", style=f"bold {accent}")

        if score and score > 0:
            if score >= 9:
                sstyle = "bold green"
            elif score >= 7:
                sstyle = "green"
            elif score >= 5:
                sstyle = "yellow"
            elif score >= 3:
                sstyle = "orange3"
            else:
                sstyle = "red"
            info_text_widget.append(f"{score}/10", style=sstyle)
        elif score == 0 or score is None:
            info_text_widget.append("None", style="dim")
        info_text_widget.append("\n")

        episodes = a.get("episodes")
        info_text_widget.append("Episodes: ", style=f"bold {primary}")
        info_text_widget.append(f"{episodes or '?'}", style=fg)

        if episodes is not None:
            if len(str(episodes)) == 1:
                pad = "     "
            elif len(str(episodes)) == 3:
                pad = "   "
            else:
                pad = "    "
        else:
            pad = "     "

        info_text_widget.append(pad)
        info_text_widget.append("|", style=f"bold {primary}")
        info_text_widget.append("   Status: ", style=f"bold {primary}")

        if status:
            info_text_widget.append(f"{status_map.get(status, status)}", style=success)
        else:
            info_text_widget.append("None", style="dim")
        info_text_widget.append("\n")

        info_text_widget.append("Genres: ", style=f"bold {secondary}")
        info_text_widget.append(f"{', '.join(a['genres']) or '?'}", style=fg)

        try:
            self.query_one("#info-text", Static).update(info_text_widget)
        except Exception:
            log.debug("ignored error", exc_info=True)

    def set_episode(self, episode, place=None) -> None:
        if not self.is_attached:
            return
        self.auto_episode = episode
        self.query_one("#episode", Input).placeholder = f"auto ({episode})"
        if place is not None:
            self.notify(f"Watch resumes episode {episode} at {format_time(place)}")

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
        try:
            details = fetch_details(self.anime["id"], self.app.token)
        except requests.RequestException:
            self.app.call_from_thread(
                self.notify, "Could not load details", severity="error"
            )
            return
        relations = relations_list(details)
        recs = recommendations_list(details)
        self.app.call_from_thread(self.fill_details, details, relations, recs)
        with ThreadPoolExecutor(max_workers=12) as pool:
            futures = {
                pool.submit(safe_cover, rel["cover_url"]): index
                for index, rel in enumerate(relations)
            }
            for future in as_completed(futures):
                cover = future.result()
                if cover is not None:
                    self.app.call_from_thread(
                        self.set_related_cover, futures[future], cover
                    )
        self.load_rec_covers(recs)

    def set_related_cover(self, index, cover) -> None:
        picture = self.related_images.get(index)
        if picture is not None and picture.is_attached:
            picture.image = fit_cover(cover, 12, 9)

    def fill_details(self, details, relations, recs) -> None:
        if not self.is_attached:
            return
        self.set_favourite(bool(details.get("isFavourite")))
        self.query_one("#info-body", Static).update(
            info_text(details, self.app.get_css_variables())
        )
        self.query_one("#staff-body").remove_children()
        staff_box = self.query_one("#staff-body")
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
        studios, producers = split_studios(details)
        box = self.query_one("#studios-box", Vertical)
        box.remove_children()
        widgets = []
        for heading, group in (("Studios", studios), ("Producers", producers)):
            widgets.append(
                Static(Text(heading, style="bold underline"), classes="section")
            )
            if not group:
                widgets.append(Static("?"))
            for s in group:
                payload = {"kind": "studio", "id": s["id"], "name": s["name"]}
                widgets.append(ClickLabel(s["name"], payload, classes="clickable"))
        box.mount(*widgets)
        self.fill_recommendations(recs)
        row = self.query_one("#related-row", HorizontalScroll)
        row.remove_children()
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
            result = toggle_favourite(self.app.token, anime_id=self.anime["id"])
        except Exception:
            self.app.call_from_thread(self.favourite_failed)
            return
        favourites = (result.get("anime") or {}).get("nodes") or []
        if not favourites:
            favourites = (result.get("manga") or {}).get("nodes") or []
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
        elif payload["kind"] == "studio":
            self.app.push_screen(StudioScreen(payload["id"], payload["name"]))
        elif payload["kind"] == "media":
            self.app.notify("Loading...", timeout=2)
            self.app.open_anime(payload["id"])
        elif payload["kind"] == "character":
            self.app.push_screen(CharacterScreen(payload["id"]))
        elif payload["kind"] == "staff":
            self.app.push_screen(StaffScreen(payload["id"]))

    def action_show_tab(self, tab_id: str) -> None:
        self.query_one(TabbedContent).active = tab_id

    def list_saved(self, result) -> None:
        if not result or not self.is_attached:
            return
        self.notify("List entry saved")
        self.load_progress()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "episode":
            self.begin_watching()

    def begin_watching(self) -> None:
        value = self.query_one("#episode", Input).value.strip()
        if value:
            if not value.isdigit() or int(value) < 1:
                self.notify("Enter a valid episode number", severity="warning")
                return
            episode = int(value)
        else:
            episode = self.auto_episode or 1
        info = self.user_info or {}
        progress = info.get("progress") or 0
        if (
            not self.app.guest
            and self.app.token
            and info.get("status") in ("PLANNING", "PAUSED", "DROPPED")
            and progress > 0
        ):
            self.query_one("#watch", Button).disabled = True
            self.resume_then_watch(episode, progress)
            return
        self.start_watching(episode)

    @work(thread=True)
    def resume_then_watch(self, episode, progress) -> None:
        try:
            save_list_entry(self.app.token, self.anime["id"], "CURRENT", progress)
        except Exception:
            self.app.call_from_thread(
                self.notify, "Could not update your AniList status", severity="warning"
            )
        else:
            self.user_info = {**(self.user_info or {}), "status": "CURRENT"}
            self.app.call_from_thread(self.update_user_info)
        self.app.call_from_thread(self.start_watching, episode)

    def start_watching(self, episode) -> None:
        if not self.is_attached:
            return
        self.query_one("#watch", Button).disabled = False
        watch(self.app, self.anime, episode)
        self.query_one("#episode", Input).value = ""
        self.load_progress()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "watch":
            self.begin_watching()
        elif event.button.id == "add":
            self.app.push_screen(ListEditorScreen(self.anime, "ANIME"), self.list_saved)
        elif event.button.id == "reset":
            forget_entry(self.anime["id"])
            self.notify("Source cleared, you will pick it again next time")
        elif event.button.id == "back":
            self.app.pop_screen()
