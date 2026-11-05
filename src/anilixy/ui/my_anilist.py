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
    Input,
    Static,
    TabbedContent,
    TabPane,
)
from textual_image.widget import Image

from anilixy.anilist.api import (
    fetch_all_anime_list,
    fetch_all_manga_list,
    fetch_favorites,
    fetch_overview,
)
from anilixy.anilist.formatting import relative_time
from anilixy.anilist.profile import fetch_profile
from anilixy.ui.animations import Backdrop
from anilixy.ui.covers import (
    cached_cover,
    cell_aspect,
    fit_cover,
    safe_cover,
    square_fit,
)
from anilixy.ui.people import CharacterScreen, StaffScreen
from anilixy.ui.studio import StudioScreen
from anilixy.ui.widgets import AvatarRow, ClickLabel

log = logging.getLogger(__name__)


COVER_WORKERS = 8


PAGE_SIZE = 25


LOAD_MORE_MARGIN = 10


class MyAniListScreen(Screen):
    BINDINGS = [
        ("escape", "app.pop_screen", "Back"),
        ("1", "show_tab('tab-overview')", "Overview"),
        ("2", "show_tab('tab-anime-list')", "Anime list"),
        ("3", "show_tab('tab-manga-list')", "Manga/Light Novel"),
        ("4", "show_tab('tab-favorites')", "Favorites"),
        ("5", "show_tab('tab-stats')", "Stats"),
    ]

    def __init__(self):
        super().__init__()
        self.activity_covers = {}
        self.avatar_rows = None
        self.all_anime_entries = []
        self.all_manga_entries = []
        self.anime_filter = "ALL"
        self.anime_search = ""
        self.manga_filter = "ALL"
        self.manga_search = ""
        self.fav_filter = "ALL"
        self.fav_search = ""
        self._search_timer = None
        self._manga_search_timer = None
        self._fav_search_timer = None
        self.paged = {}

    def compose(self) -> ComposeResult:
        name = (self.app.profile or {}).get("name")
        title = f"My AniList · {name}" if name else "My AniList"

        yield Backdrop()
        with Vertical(id="my-body"):
            yield Static(Text(title), id="my-title")

            with TabbedContent(id="my-tabs"):
                with TabPane("Overview", id="tab-overview"):
                    with Horizontal(id="overview-row"):
                        with VerticalScroll(id="activity-column"):
                            yield Static("Latest additions", classes="section")
                            with Vertical(id="activity-list"):
                                yield Static(
                                    "Loading latest additions...",
                                    classes="my-placeholder",
                                )
                        with VerticalScroll(id="profile-column"):
                            with AvatarRow(id="avatar-row"):
                                yield Image(id="overview-avatar")
                            yield Static(Text(name or "Loading..."), id="overview-name")
                            yield Static(Text("Loading..."), id="overview-counts")
                            yield Static("Genre overview", classes="section")
                            with VerticalScroll(id="genre-list"):
                                yield Static("Loading...", classes="my-placeholder")

                with TabPane("Anime list", id="tab-anime-list"):
                    with Vertical(id="anime-list-wrap"):
                        with Horizontal(id="anime-list-controls"):
                            yield Button("All", id="al-filter-all", variant="primary")
                            yield Button("Watching", id="al-filter-CURRENT")
                            yield Button("Completed", id="al-filter-COMPLETED")
                            yield Button("Dropped", id="al-filter-DROPPED")
                            yield Button("Planning", id="al-filter-PLANNING")
                            yield Button("Paused", id="al-filter-PAUSED")
                            yield Button("Rewatching", id="al-filter-REPEATING")
                        yield Input(
                            placeholder="Search anime...", id="anime-list-search"
                        )
                        yield Static("Loading...", id="anime-list-count")
                        with VerticalScroll(id="anime-list-scroll"):
                            yield Static("Loading...", classes="my-placeholder")

                with TabPane("Manga/Light Novel", id="tab-manga-list"):
                    with Vertical(id="manga-list-wrap"):
                        with Horizontal(id="ml-filter-controls"):
                            yield Button("All", id="ml-filter-all", variant="primary")
                            yield Button("Reading", id="ml-filter-CURRENT")
                            yield Button("Completed", id="ml-filter-COMPLETED")
                            yield Button("Dropped", id="ml-filter-DROPPED")
                            yield Button("Planning", id="ml-filter-PLANNING")
                            yield Button("Paused", id="ml-filter-PAUSED")
                            yield Button("Rereading", id="ml-filter-REPEATING")
                        yield Input(
                            placeholder="Search manga/light novel...",
                            id="manga-list-search",
                        )
                        yield Static("Loading...", id="manga-list-count")
                        with VerticalScroll(id="manga-list-scroll"):
                            yield Static("Loading...", classes="my-placeholder")

                with TabPane("Favorites", id="tab-favorites"):
                    with Vertical(id="fav-wrap"):
                        with Horizontal(id="fav-filter-controls"):
                            yield Button("All", id="fav-filter-ALL", variant="primary")
                            yield Button("Anime", id="fav-filter-ANIME")
                            yield Button("Manga/LN", id="fav-filter-MANGA")
                            yield Button("Characters", id="fav-filter-CHARACTER")
                            yield Button("Staff", id="fav-filter-STAFF")
                            yield Button("Studios", id="fav-filter-STUDIO")
                        yield Input(placeholder="Search favorites...", id="fav-search")
                        yield Static("Loading...", id="fav-count")
                        with VerticalScroll(id="fav-scroll"):
                            yield Static("Loading...", classes="my-placeholder")

                with TabPane("Stats", id="tab-stats"):
                    with Horizontal(id="stats-row"):
                        with VerticalScroll(id="stats-anime", classes="stats-col"):
                            yield Static("Anime Statistics", classes="stats-title")
                            yield Static("Loading...", id="stats-anime-text")
                            yield Static("", id="stats-anime-buckets")
                            yield Static("", id="stats-anime-status")
                            yield Static("", id="stats-anime-formats")
                        with VerticalScroll(id="stats-manga", classes="stats-col"):
                            yield Static("Manga Statistics", classes="stats-title")
                            yield Static("Loading...", id="stats-manga-text")
                            yield Static("", id="stats-manga-buckets")
                            yield Static("", id="stats-manga-status")
                            yield Static("", id="stats-manga-formats")

            yield Static("1-5: tabs  |  Esc: back", id="my-hint")

    def on_mount(self) -> None:
        self.update_overview_layout(self.size.width)
        for kind, scroll_id in (
            ("anime", "#anime-list-scroll"),
            ("manga", "#manga-list-scroll"),
            ("fav", "#fav-scroll"),
        ):
            self.watch(
                self.query_one(scroll_id, VerticalScroll),
                "scroll_y",
                self.scroll_watcher(kind),
                init=False,
            )
        self.load_overview()
        if not self.app.guest:
            self.set_timer(0.1, self.load_anime_list)
            self.set_timer(0.2, self.load_manga_list)
            self.set_timer(0.3, self.load_favorites)

    def on_resize(self, event) -> None:
        self.update_overview_layout(event.size.width)

    def fit_avatar(self) -> None:
        if not self.is_attached:
            return
        avatar = self.query_one("#overview-avatar", Image)
        width = avatar.size.width
        if width <= 0:
            return
        rows = max(4, round(width / cell_aspect()))
        if rows != self.avatar_rows:
            self.avatar_rows = rows
            avatar.styles.height = rows

    def update_overview_layout(self, width: int) -> None:
        for row in self.query("#overview-row"):
            row.set_class(width < 70, "narrow-overview")

    def action_show_tab(self, tab_id: str) -> None:
        self.query_one("#my-tabs", TabbedContent).active = tab_id

    @work(thread=True)
    def load_overview(self) -> None:
        profile = self.app.profile
        if not profile or "id" not in profile:
            try:
                profile = fetch_profile(self.app.token)
            except requests.RequestException:
                self.app.call_from_thread(self.overview_failed)
                return
            if profile is None:
                self.app.call_from_thread(self.overview_failed)
                return
        try:
            data = fetch_overview(self.app.token, profile["id"])
        except requests.RequestException:
            self.app.call_from_thread(self.overview_failed)
            return
        if data is None:
            self.app.call_from_thread(self.overview_failed)
            return
        viewer = data["profile"]
        activities = data["activities"]
        self.app.call_from_thread(self.fill_overview, viewer, activities)
        avatar_data = viewer.get("avatar") or {}
        avatar_url = avatar_data.get("large") or avatar_data.get("medium")
        avatar = safe_cover(avatar_url) if avatar_url else None
        if avatar is not None:
            self.app.call_from_thread(self.set_overview_avatar, avatar)
        cover_urls = {}
        for activity in activities:
            media = activity.get("media") or {}
            url = (media.get("coverImage") or {}).get("large")
            if media.get("id") is not None and url:
                cover_urls[media["id"]] = url
        with ThreadPoolExecutor(max_workers=12) as pool:
            futures = {
                pool.submit(safe_cover, url): media_id
                for media_id, url in cover_urls.items()
            }
            for future in as_completed(futures):
                cover = future.result()
                if cover is not None:
                    self.app.call_from_thread(
                        self.set_activity_cover, futures[future], cover
                    )

    def fill_overview(self, profile, activities) -> None:
        if not self.is_attached:
            return
        self.app.profile = profile
        self.query_one("#overview-name", Static).update(
            Text(profile.get("name") or "?")
        )
        stats = profile.get("statistics") or {}
        anime = stats.get("anime") or {}
        manga = stats.get("manga") or {}
        counts = Text()
        counts.append("Anime watched\n", style="bold")
        counts.append(
            f"{anime.get('count') or 0} titles · {anime.get('episodesWatched') or 0} episodes\n",
            style="dim",
        )
        counts.append("Manga read\n", style="bold")
        counts.append(
            f"{manga.get('count') or 0} titles · {manga.get('chaptersRead') or 0} chapters",
            style="dim",
        )
        self.query_one("#overview-counts", Static).update(counts)
        genres = {}
        for group in (anime, manga):
            for genre in group.get("genres") or []:
                name = genre.get("genre")
                if name:
                    genres[name] = genres.get(name, 0) + (genre.get("count") or 0)
        all_genres = [
            {"genre": name, "count": count}
            for name, count in sorted(
                genres.items(), key=lambda item: item[1], reverse=True
            )
        ]
        genre_box = self.query_one("#genre-list", VerticalScroll)
        genre_box.remove_children()
        if not all_genres:
            genre_box.mount(Static("No genre data", classes="my-placeholder"))
        else:
            highest = max((genre.get("count") or 0) for genre in all_genres) or 1
            text = Text()
            for index, genre in enumerate(all_genres):
                count = genre.get("count") or 0
                bar = max(1, round(count / highest * 10))
                text.append(f"{genre.get('genre') or '?':<13} ", style="bold")
                text.append("█" * bar, style="bold")
                text.append(f" {count}", style="dim")
                if index < len(all_genres) - 1:
                    text.append("\n\n")
            genre_box.mount(Static(text, classes="genre-overview"))
        activity_list = self.query_one("#activity-list", Vertical)
        activity_list.remove_children()
        self.activity_covers = {}
        if not activities:
            activity_list.mount(Static("No recent activity", classes="my-placeholder"))
            return
        activity_list.mount(
            *[self.build_activity_row(activity) for activity in activities]
        )

    def build_activity_row(self, activity):
        media = activity.get("media") or {}
        title = (
            (media.get("title") or {}).get("english")
            or (media.get("title") or {}).get("romaji")
            or "?"
        )
        media_id = media.get("id")
        media_type = media.get("type")
        picture = Image(classes="activity-cover")
        url = (media.get("coverImage") or {}).get("large")
        if media_id is not None and url:
            self.activity_covers.setdefault(media_id, []).append(picture)
        payload = (
            {"kind": "media", "id": media_id}
            if media_id is not None
            else {"kind": "missing"}
        )
        title_label = ClickLabel(title, payload, classes="clickable activity-title")
        detail = Static(Text(self.activity_detail(activity)), classes="activity-detail")
        meta = Text()
        fmt = (media.get("format") or "").upper()
        if media_type == "MANGA":
            if fmt == "NOVEL":
                meta.append("Light novel", style="bold")
            else:
                meta.append("Manga", style="bold")
        elif media_type == "ANIME":
            meta.append("Anime", style="bold")
        else:
            meta.append(
                media_type.capitalize() if media_type else "Unknown", style="bold"
            )
        when = relative_time(activity.get("createdAt"))
        if when:
            meta.append(" · ", style="dim")
            meta.append(when, style="dim")
        info = Vertical(
            title_label,
            detail,
            Static(meta, classes="activity-meta"),
            classes="activity-info",
        )
        return Horizontal(picture, info, classes="activity-row")

    def activity_detail(self, activity):
        media = activity.get("media") or {}
        status = (activity.get("status") or "").strip()
        progress = activity.get("progress")
        total = (
            media.get("episodes")
            if media.get("type") == "ANIME"
            else media.get("chapters")
        )
        if not status:
            return "Activity"
        if progress:
            progress_text = str(progress)
            if " - " in progress_text:
                status = status.replace("episode", "episodes").replace(
                    "chapter", "chapters"
                )
                detail = f"{status.capitalize()} {progress_text}"
                if total:
                    detail += f" of {total}"
                return detail
            detail = f"{status.capitalize()} {progress_text}"
            if total:
                detail += f"/{total}"
            return detail
        return status.capitalize()

    def set_overview_avatar(self, cover) -> None:
        if not self.is_attached:
            return
        side = min(cover.size)
        left = (cover.width - side) // 2
        top = (cover.height - side) // 2
        square = cover.crop((left, top, left + side, top + side))
        avatar = self.query_one("#overview-avatar", Image)
        cols = min(avatar.size.width or 30, 38)
        avatar.image = square_fit(square, cols)

    def set_activity_cover(self, media_id, cover) -> None:
        if not self.is_attached:
            return
        for picture in self.activity_covers.get(media_id, []):
            if picture.is_attached:
                picture.image = fit_cover(cover, 11, 8)

    @work(thread=True)
    def load_anime_list(self) -> None:
        profile = self.app.profile
        if not profile or "id" not in profile:
            try:
                profile = fetch_profile(self.app.token)
            except Exception:
                self.app.call_from_thread(self.anime_list_failed)
                return
            if profile is None:
                self.app.call_from_thread(self.anime_list_failed)
                return
        try:
            entries = fetch_all_anime_list(self.app.token, profile["id"])
        except Exception as e:
            self.app.call_from_thread(self.notify, f"Error: {e}", severity="error")
            self.app.call_from_thread(self.anime_list_failed)
            return
        self.app.call_from_thread(self.fill_anime_list, entries)

    def anime_list_failed(self) -> None:
        if not self.is_attached:
            return
        try:
            self.query_one("#anime-list-count", Static).update("Failed to load")
            scroll = self.query_one("#anime-list-scroll", VerticalScroll)
            scroll.remove_children()
            scroll.mount(Static("Could not load anime list", classes="my-placeholder"))
        except Exception:
            log.debug("ignored error", exc_info=True)

    def fill_anime_list(self, entries) -> None:
        if not self.is_attached:
            return
        self.all_anime_entries = entries or []
        self.render_anime_list()
        self.render_stats()

    ANIME_STATUS = {
        "CURRENT": "Watching",
        "COMPLETED": "Completed",
        "PAUSED": "On Hold",
        "DROPPED": "Dropped",
        "PLANNING": "Planning",
        "REPEATING": "Rewatching",
    }

    MANGA_STATUS = {
        "CURRENT": "Reading",
        "COMPLETED": "Completed",
        "PAUSED": "Paused",
        "DROPPED": "Dropped",
        "PLANNING": "Planning",
        "REPEATING": "Rereading",
    }

    def scroll_watcher(self, kind):
        def watcher() -> None:
            self.load_more_if_needed(kind)

        return watcher

    def start_paged(self, kind, scroll, items, build) -> None:
        state = {
            "kind": kind,
            "items": items,
            "shown": 0,
            "build": build,
            "scroll": scroll,
            "busy": False,
        }
        self.paged[kind] = state
        self.mount_chunk(state)

    def mount_chunk(self, state) -> None:
        start = state["shown"]
        chunk = state["items"][start : start + PAGE_SIZE]
        if not chunk:
            return
        state["shown"] = start + len(chunk)
        state["busy"] = True
        rows = []
        wanted = []
        for item in chunk:
            row, picture, url = state["build"](item)
            rows.append(row)
            if not url:
                continue
            cover = cached_cover(url)
            if cover is not None:
                picture.image = fit_cover(cover, 8, 6)
            else:
                wanted.append((picture, url))
        state["scroll"].mount(*rows)
        self.set_timer(0.2, lambda: self.release_chunk(state))
        if wanted:
            self.fetch_covers(state, wanted)

    def release_chunk(self, state) -> None:
        state["busy"] = False
        scroll = state["scroll"]
        if scroll.size.height > 0 and scroll.max_scroll_y <= 0:
            self.load_more_if_needed(state["kind"])

    def load_more_if_needed(self, kind) -> None:
        state = self.paged.get(kind)
        if state is None or state["busy"] or not self.is_attached:
            return
        if state["shown"] >= len(state["items"]):
            return
        scroll = state["scroll"]
        if scroll.size.height <= 0:
            return
        if scroll.max_scroll_y - scroll.scroll_y <= LOAD_MORE_MARGIN:
            self.mount_chunk(state)

    @work(thread=True)
    def fetch_covers(self, state, wanted) -> None:
        def fetch(url):
            if self.paged.get(state["kind"]) is not state:
                return None
            return safe_cover(url)

        with ThreadPoolExecutor(max_workers=COVER_WORKERS) as pool:
            futures = {pool.submit(fetch, url): picture for picture, url in wanted}
            for future in as_completed(futures):
                cover = future.result()
                if cover is not None:
                    self.app.call_from_thread(self.apply_cover, futures[future], cover)

    def apply_cover(self, picture, cover) -> None:
        if picture.is_attached:
            picture.image = fit_cover(cover, 8, 6)

    def media_title(self, media) -> str:
        titles = media.get("title") or {}
        return titles.get("english") or titles.get("romaji") or "?"

    def render_anime_list(self) -> None:
        if not self.is_attached:
            return
        try:
            scroll = self.query_one("#anime-list-scroll", VerticalScroll)
            count_label = self.query_one("#anime-list-count", Static)
            search_input = self.query_one("#anime-list-search", Input)
        except Exception:
            return
        self.anime_search = (search_input.value or "").lower().strip()
        items = []
        for entry in self.all_anime_entries:
            if (
                self.anime_filter != "ALL"
                and (entry.get("status") or "") != self.anime_filter
            ):
                continue
            media = entry.get("media") or {}
            title = self.media_title(media)
            if self.anime_search and self.anime_search not in title.lower():
                continue
            items.append((title.lower(), title, media, entry))
        items.sort(key=lambda x: x[0])
        count_label.update(f"{len(items)} anime")
        scroll.remove_children()
        scroll.scroll_home(animate=False)
        self.paged.pop("anime", None)
        if not items:
            scroll.mount(Static("No results", classes="my-placeholder"))
            return
        self.start_paged("anime", scroll, items, self.build_anime_row)

    def build_anime_row(self, item):
        _, title, media, entry = item
        media_id = media.get("id")
        status = entry.get("status") or ""
        progress = entry.get("progress") or 0
        total = media.get("episodes")
        repeat = entry.get("repeat") or 0
        meta = f"{self.ANIME_STATUS.get(status, status)} · {progress}/{total or '?'}"
        if repeat > 0:
            meta += f" · ↻{repeat}"
        picture = Image(classes="anime-list-cover")
        info = Vertical(
            ClickLabel(
                title,
                {"kind": "media", "id": media_id},
                classes="clickable anime-list-title",
            ),
            Static(Text(meta, style="dim"), classes="anime-list-meta"),
            classes="anime-list-info",
        )
        row = Horizontal(picture, info, classes="anime-list-row")
        return row, picture, (media.get("coverImage") or {}).get("large")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id.startswith("al-filter-"):
            self.anime_filter = (
                "ALL"
                if button_id == "al-filter-all"
                else button_id.replace("al-filter-", "")
            )
            for bid in [
                "al-filter-all",
                "al-filter-CURRENT",
                "al-filter-COMPLETED",
                "al-filter-DROPPED",
                "al-filter-PLANNING",
                "al-filter-PAUSED",
                "al-filter-REPEATING",
            ]:
                try:
                    btn = self.query_one(f"#{bid}", Button)
                    btn.variant = "primary" if bid == button_id else "default"
                except Exception:
                    log.debug("ignored error", exc_info=True)
            self.render_anime_list()
            return
        if button_id.startswith("ml-filter-"):
            self.manga_filter = (
                "ALL"
                if button_id == "ml-filter-all"
                else button_id.replace("ml-filter-", "")
            )
            for bid in [
                "ml-filter-all",
                "ml-filter-CURRENT",
                "ml-filter-COMPLETED",
                "ml-filter-DROPPED",
                "ml-filter-PLANNING",
                "ml-filter-PAUSED",
                "ml-filter-REPEATING",
            ]:
                try:
                    btn = self.query_one(f"#{bid}", Button)
                    btn.variant = "primary" if bid == button_id else "default"
                except Exception:
                    log.debug("ignored error", exc_info=True)
            self.render_manga_list()
            return
        if button_id.startswith("fav-filter-"):
            self.fav_filter = button_id.replace("fav-filter-", "")
            for bid in [
                "fav-filter-ALL",
                "fav-filter-ANIME",
                "fav-filter-MANGA",
                "fav-filter-CHARACTER",
                "fav-filter-STAFF",
                "fav-filter-STUDIO",
            ]:
                try:
                    btn = self.query_one(f"#{bid}", Button)
                    btn.variant = "primary" if bid == button_id else "default"
                except Exception:
                    log.debug("ignored error", exc_info=True)
            self.render_favorites()
            return

    @work(thread=True)
    def load_manga_list(self) -> None:
        profile = self.app.profile
        if not profile or "id" not in profile:
            try:
                profile = fetch_profile(self.app.token)
            except Exception:
                self.app.call_from_thread(self.manga_list_failed)
                return
            if profile is None:
                self.app.call_from_thread(self.manga_list_failed)
                return
        try:
            entries = fetch_all_manga_list(self.app.token, profile["id"])
        except Exception as e:
            self.app.call_from_thread(self.notify, f"Error: {e}", severity="error")
            self.app.call_from_thread(self.manga_list_failed)
            return
        self.app.call_from_thread(self.fill_manga_list, entries)

    def manga_list_failed(self) -> None:
        if not self.is_attached:
            return
        try:
            self.query_one("#manga-list-count", Static).update("Failed to load")
            scroll = self.query_one("#manga-list-scroll", VerticalScroll)
            scroll.remove_children()
            scroll.mount(Static("Could not load manga list", classes="my-placeholder"))
        except Exception:
            log.debug("ignored error", exc_info=True)

    def fill_manga_list(self, entries) -> None:
        if not self.is_attached:
            return
        self.all_manga_entries = entries or []
        self.render_manga_list()
        self.render_stats()

    def render_manga_list(self) -> None:
        if not self.is_attached:
            return
        try:
            scroll = self.query_one("#manga-list-scroll", VerticalScroll)
            count_label = self.query_one("#manga-list-count", Static)
            search_input = self.query_one("#manga-list-search", Input)
        except Exception:
            return
        self.manga_search = (search_input.value or "").lower().strip()
        items = []
        for entry in self.all_manga_entries:
            if (
                self.manga_filter != "ALL"
                and (entry.get("status") or "") != self.manga_filter
            ):
                continue
            media = entry.get("media") or {}
            title = self.media_title(media)
            if self.manga_search and self.manga_search not in title.lower():
                continue
            items.append((title.lower(), title, media, entry))
        items.sort(key=lambda x: x[0])
        count_label.update(f"{len(items)} manga")
        scroll.remove_children()
        scroll.scroll_home(animate=False)
        self.paged.pop("manga", None)
        if not items:
            scroll.mount(Static("No results", classes="my-placeholder"))
            return
        self.start_paged("manga", scroll, items, self.build_manga_row)

    def build_manga_row(self, item):
        _, title, media, entry = item
        media_id = media.get("id")
        status = entry.get("status") or ""
        progress = entry.get("progress") or 0
        progress_vol = entry.get("progressVolumes") or 0
        total_ch = media.get("chapters")
        total_vol = media.get("volumes")
        fmt = (media.get("format") or "").replace("_", " ")
        repeat = entry.get("repeat") or 0
        meta = self.MANGA_STATUS.get(status, status)
        if fmt:
            meta += f" · {fmt}"
        meta += f" · Ch {progress}/{total_ch or '?'} · Vol {progress_vol}/{total_vol or '?'}"
        if repeat > 0:
            meta += f" · ↻{repeat}"
        picture = Image(classes="manga-list-cover")
        info = Vertical(
            ClickLabel(
                title,
                {"kind": "media", "id": media_id},
                classes="clickable manga-list-title",
            ),
            Static(Text(meta, style="dim"), classes="manga-list-meta"),
            classes="manga-list-info",
        )
        row = Horizontal(picture, info, classes="manga-list-row")
        return row, picture, (media.get("coverImage") or {}).get("large")

    @work(thread=True)
    def load_favorites(self) -> None:
        profile = self.app.profile
        if not profile or "id" not in profile:
            try:
                profile = fetch_profile(self.app.token)
            except Exception:
                return
            if profile is None:
                return
        try:
            raw_favs = fetch_favorites(self.app.token, profile["id"])
        except Exception:
            self.app.call_from_thread(
                self.notify, "Failed to load favorites", severity="error"
            )
            return
        self.app.call_from_thread(self.fill_favorites, raw_favs)

    def fill_favorites(self, raw_favs) -> None:
        if not self.is_attached:
            return
        self.all_favs = []
        for a in raw_favs.get("anime", {}).get("nodes", []):
            self.all_favs.append(
                {
                    "id": a["id"],
                    "type": "ANIME",
                    "title": a["title"]["english"] or a["title"]["romaji"] or "?",
                    "subtitle": (a.get("format") or "Anime").replace("_", " ").title(),
                    "cover_url": (a.get("coverImage") or {}).get("large"),
                }
            )
        for m in raw_favs.get("manga", {}).get("nodes", []):
            fmt = "Light Novel" if m.get("format") == "NOVEL" else "Manga"
            self.all_favs.append(
                {
                    "id": m["id"],
                    "type": "MANGA",
                    "title": m["title"]["english"] or m["title"]["romaji"] or "?",
                    "subtitle": fmt,
                    "cover_url": (m.get("coverImage") or {}).get("large"),
                }
            )
        for c in raw_favs.get("characters", {}).get("nodes", []):
            self.all_favs.append(
                {
                    "id": c["id"],
                    "type": "CHARACTER",
                    "title": c["name"]["full"] or "?",
                    "subtitle": "Character",
                    "cover_url": (c.get("image") or {}).get("large"),
                }
            )
        for s in raw_favs.get("staff", {}).get("nodes", []):
            self.all_favs.append(
                {
                    "id": s["id"],
                    "type": "STAFF",
                    "title": s["name"]["full"] or "?",
                    "subtitle": "Staff",
                    "cover_url": (s.get("image") or {}).get("large"),
                }
            )
        for st in raw_favs.get("studios", {}).get("nodes", []):
            self.all_favs.append(
                {
                    "id": st["id"],
                    "type": "STUDIO",
                    "title": st.get("name") or "?",
                    "subtitle": "Studio",
                    "cover_url": None,
                }
            )
        self.render_favorites()

    def render_favorites(self) -> None:
        if not self.is_attached:
            return
        try:
            scroll = self.query_one("#fav-scroll", VerticalScroll)
            count_label = self.query_one("#fav-count", Static)
            search_input = self.query_one("#fav-search", Input)
        except Exception:
            return
        self.fav_search = (search_input.value or "").lower().strip()
        items = []
        for item in getattr(self, "all_favs", []):
            if self.fav_filter != "ALL" and item["type"] != self.fav_filter:
                continue
            if self.fav_search and self.fav_search not in item["title"].lower():
                continue
            items.append(item)
        items.sort(key=lambda x: x["title"].lower())
        count_label.update(f"{len(items)} favorites")
        scroll.remove_children()
        scroll.scroll_home(animate=False)
        self.paged.pop("fav", None)
        if not items:
            scroll.mount(Static("No favorites found", classes="my-placeholder"))
            return
        self.start_paged("fav", scroll, items, self.build_fav_row)

    def build_fav_row(self, item):
        picture = Image(classes="fav-cover")
        info = Vertical(
            ClickLabel(
                item["title"],
                {"kind": item["type"].lower(), "id": item["id"]},
                classes="clickable fav-title",
            ),
            Static(Text(item["subtitle"], style="dim"), classes="fav-meta"),
            classes="fav-info",
        )
        row = Horizontal(picture, info, classes="fav-row")
        return row, picture, item["cover_url"]

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "anime-list-search":
            if hasattr(self, "_search_timer") and self._search_timer is not None:
                try:
                    self._search_timer.stop()
                except Exception:
                    log.debug("ignored error", exc_info=True)
            self._search_timer = self.set_timer(0.15, self.render_anime_list)
            return
        if event.input.id == "manga-list-search":
            if (
                hasattr(self, "_manga_search_timer")
                and self._manga_search_timer is not None
            ):
                try:
                    self._manga_search_timer.stop()
                except Exception:
                    log.debug("ignored error", exc_info=True)
            self._manga_search_timer = self.set_timer(0.15, self.render_manga_list)
            return
        if event.input.id == "fav-search":
            if (
                hasattr(self, "_fav_search_timer")
                and self._fav_search_timer is not None
            ):
                try:
                    self._fav_search_timer.stop()
                except Exception:
                    log.debug("ignored error", exc_info=True)
            self._fav_search_timer = self.set_timer(0.15, self.render_favorites)
            return

    def overview_failed(self) -> None:
        if not self.is_attached:
            return
        name = (self.app.profile or {}).get("name")
        self.query_one("#overview-name", Static).update(
            Text(name or "Profile unavailable")
        )
        self.query_one("#overview-counts", Static).update(
            Text("Could not load profile", style="dim")
        )
        genre_box = self.query_one("#genre-list", VerticalScroll)
        genre_box.remove_children()
        genre_box.mount(Static("Could not load genres", classes="my-placeholder"))
        activity_list = self.query_one("#activity-list", Vertical)
        activity_list.remove_children()
        activity_list.mount(
            Static("Could not load latest additions", classes="my-placeholder")
        )

    def on_click_label_pressed(self, event) -> None:
        payload = event.label.payload
        if payload["kind"] in ("media", "anime", "manga"):
            self.app.notify("Loading...", timeout=2)
            self.app.open_anime(payload["id"])
        elif payload["kind"] == "character":
            self.app.push_screen(CharacterScreen(payload["id"]))
        elif payload["kind"] == "staff":
            self.app.push_screen(StaffScreen(payload["id"]))
        elif payload["kind"] == "studio":
            name = "Studio"
            for item in getattr(self, "all_favs", []):
                if item["id"] == payload["id"]:
                    name = item["title"]
                    break
            self.app.push_screen(StudioScreen(payload["id"], name))
        else:
            self.notify("This entry is no longer available on AniList", severity="warning")

    def render_stats(self) -> None:
        if not self.is_attached:
            return
        anime_entries = getattr(self, "all_anime_entries", [])
        manga_entries = getattr(self, "all_manga_entries", [])

        if not anime_entries and not manga_entries:
            return

        a_count = len(anime_entries)
        a_eps = sum((e.get("progress") or 0) for e in anime_entries)
        a_days = round(a_eps * 24 / 60 / 24, 1)
        a_scores = [
            e.get("score")
            for e in anime_entries
            if e.get("score") and e.get("score") > 0
        ]
        a_mean = sum(a_scores) / len(a_scores) if a_scores else 0

        a_status = {}
        a_buckets = {
            "1": 0,
            "2-6": 0,
            "7-16": 0,
            "17-28": 0,
            "29-55": 0,
            "56-100": 0,
            "101+": 0,
        }
        a_formats = {}

        for e in anime_entries:
            status = e.get("status") or "UNKNOWN"
            a_status[status] = a_status.get(status, 0) + 1

            media = e.get("media") or {}
            fmt = media.get("format") or "UNKNOWN"
            a_formats[fmt] = a_formats.get(fmt, 0) + 1

            total = media.get("episodes")
            if total is not None:
                if total == 1:
                    a_buckets["1"] += 1
                elif total <= 6:
                    a_buckets["2-6"] += 1
                elif total <= 16:
                    a_buckets["7-16"] += 1
                elif total <= 28:
                    a_buckets["17-28"] += 1
                elif total <= 55:
                    a_buckets["29-55"] += 1
                elif total <= 100:
                    a_buckets["56-100"] += 1
                else:
                    a_buckets["101+"] += 1

        a_text = Text()
        a_text.append("Total Anime:       ", style="bold")
        a_text.append(f"{a_count}\n", style="cyan")
        a_text.append("Episodes Watched:  ", style="bold")
        a_text.append(f"{a_eps}\n", style="cyan")
        a_text.append("Days Watched:      ", style="bold")
        a_text.append(f"{a_days}\n", style="cyan")
        a_text.append("Mean Score:        ", style="bold")
        a_text.append(f"{a_mean:.1f}\n", style="cyan")
        self.query_one("#stats-anime-text", Static).update(a_text)

        a_chart = Text("Episode Count Distribution\n\n", style="bold underline")
        max_a_bucket = max(a_buckets.values()) if a_buckets else 1
        total_a_entries = sum(a_buckets.values()) or 1
        for label, count in a_buckets.items():
            pct = count / total_a_entries
            bar_len = (
                int((count / max_a_bucket) * 15)
                if max_a_bucket > 0 and count > 0
                else 0
            )
            bar = "━" * bar_len
            a_chart.append(f"{label:<8} ", style="dim")
            a_chart.append(f"{bar:<16}", style="cyan")
            a_chart.append(f" {count} ({pct * 100:.0f}%)\n", style="bold")
        self.query_one("#stats-anime-buckets", Static).update(a_chart)

        a_stat_text = Text("Status Distribution\n\n", style="bold underline")
        a_colors = {
            "COMPLETED": "green",
            "CURRENT": "blue",
            "PLANNING": "yellow",
            "DROPPED": "red",
            "PAUSED": "purple",
            "REPEATING": "cyan",
        }
        all_a_statuses = [
            "COMPLETED",
            "CURRENT",
            "PLANNING",
            "DROPPED",
            "PAUSED",
            "REPEATING",
        ]
        all_a_statuses.sort(key=lambda x: a_status.get(x, 0), reverse=True)
        total_a_status = sum(a_status.values()) or 1
        for st in all_a_statuses:
            cnt = a_status.get(st, 0)
            pct = cnt / total_a_status
            color = a_colors.get(st, "white")
            bar_len = int(pct * 15)
            bar = "━" * bar_len
            a_stat_text.append(f"{st.title():<12} ", style="bold")
            a_stat_text.append(f"{bar:<16}", style=color)
            a_stat_text.append(f" {cnt} ({pct * 100:.0f}%)\n")
        self.query_one("#stats-anime-status", Static).update(a_stat_text)

        a_fmt_text = Text("Format Distribution\n\n", style="bold underline")
        all_a_formats = [
            "TV",
            "TV_SHORT",
            "MOVIE",
            "SPECIAL",
            "OVA",
            "ONA",
            "MUSIC",
            "UNKNOWN",
        ]
        all_a_formats.sort(key=lambda x: a_formats.get(x, 0), reverse=True)
        total_a_fmt = sum(a_formats.values()) or 1
        for fmt in all_a_formats:
            cnt = a_formats.get(fmt, 0)
            pct = cnt / total_a_fmt
            fmt_name = fmt.replace("_", " ").title()
            bar_len = int(pct * 15)
            bar = "━" * bar_len
            a_fmt_text.append(f"{fmt_name:<12} ", style="bold")
            a_fmt_text.append(f"{bar:<16}", style="cyan")
            a_fmt_text.append(f" {cnt} ({pct * 100:.0f}%)\n")
        self.query_one("#stats-anime-formats", Static).update(a_fmt_text)

        m_count = len(manga_entries)
        m_chaps = sum((e.get("progress") or 0) for e in manga_entries)
        m_vols = sum((e.get("progressVolumes") or 0) for e in manga_entries)
        m_scores = [
            e.get("score")
            for e in manga_entries
            if e.get("score") and e.get("score") > 0
        ]
        m_mean = sum(m_scores) / len(m_scores) if m_scores else 0

        m_status = {}
        m_buckets = {
            "1": 0,
            "2-5": 0,
            "6-10": 0,
            "11-25": 0,
            "26-50": 0,
            "51-100": 0,
            "101-200": 0,
            "201+": 0,
            "Unknown": 0,
        }
        m_formats = {}

        for e in manga_entries:
            status = e.get("status") or "UNKNOWN"
            m_status[status] = m_status.get(status, 0) + 1

            media = e.get("media") or {}
            fmt = media.get("format") or "UNKNOWN"
            m_formats[fmt] = m_formats.get(fmt, 0) + 1

            total = media.get("chapters")
            if total is None:
                m_buckets["Unknown"] += 1
            elif total == 1:
                m_buckets["1"] += 1
            elif total <= 5:
                m_buckets["2-5"] += 1
            elif total <= 10:
                m_buckets["6-10"] += 1
            elif total <= 25:
                m_buckets["11-25"] += 1
            elif total <= 50:
                m_buckets["26-50"] += 1
            elif total <= 100:
                m_buckets["51-100"] += 1
            elif total <= 200:
                m_buckets["101-200"] += 1
            else:
                m_buckets["201+"] += 1

        m_text = Text()
        m_text.append("Total Manga:       ", style="bold")
        m_text.append(f"{m_count}\n", style="magenta")
        m_text.append("Chapters Read:     ", style="bold")
        m_text.append(f"{m_chaps}\n", style="magenta")
        m_text.append("Volumes Read:      ", style="bold")
        m_text.append(f"{m_vols}\n", style="magenta")
        m_text.append("Mean Score:        ", style="bold")
        m_text.append(f"{m_mean:.1f}\n", style="magenta")
        self.query_one("#stats-manga-text", Static).update(m_text)

        m_chart = Text("Chapter Count Distribution\n\n", style="bold underline")
        max_m_bucket = max(m_buckets.values()) if m_buckets else 1
        total_m_entries = sum(m_buckets.values()) or 1
        for label, count in m_buckets.items():
            pct = count / total_m_entries
            bar_len = (
                int((count / max_m_bucket) * 15)
                if max_m_bucket > 0 and count > 0
                else 0
            )
            bar = "━" * bar_len
            m_chart.append(f"{label:<9} ", style="dim")
            m_chart.append(f"{bar:<16}", style="magenta")
            m_chart.append(f" {count} ({pct * 100:.0f}%)\n", style="bold")
        self.query_one("#stats-manga-buckets", Static).update(m_chart)

        m_stat_text = Text("Status Distribution\n\n", style="bold underline")
        m_colors = {
            "COMPLETED": "green",
            "CURRENT": "blue",
            "PLANNING": "yellow",
            "DROPPED": "red",
            "PAUSED": "purple",
            "REPEATING": "cyan",
        }
        all_m_statuses = [
            "COMPLETED",
            "CURRENT",
            "PLANNING",
            "DROPPED",
            "PAUSED",
            "REPEATING",
        ]
        all_m_statuses.sort(key=lambda x: m_status.get(x, 0), reverse=True)
        total_m_status = sum(m_status.values()) or 1
        for st in all_m_statuses:
            cnt = m_status.get(st, 0)
            pct = cnt / total_m_status
            color = m_colors.get(st, "white")
            bar_len = int(pct * 15)
            bar = "━" * bar_len
            m_stat_text.append(f"{st.title():<12} ", style="bold")
            m_stat_text.append(f"{bar:<16}", style=color)
            m_stat_text.append(f" {cnt} ({pct * 100:.0f}%)\n")
        self.query_one("#stats-manga-status", Static).update(m_stat_text)

        m_fmt_text = Text("Format Distribution\n\n", style="bold underline")
        all_m_formats = ["MANGA", "NOVEL", "ONE_SHOT", "UNKNOWN"]
        all_m_formats.sort(key=lambda x: m_formats.get(x, 0), reverse=True)
        total_m_fmt = sum(m_formats.values()) or 1
        for fmt in all_m_formats:
            cnt = m_formats.get(fmt, 0)
            pct = cnt / total_m_fmt
            fmt_name = fmt.replace("_", " ").title()
            bar_len = int(pct * 15)
            bar = "━" * bar_len
            m_fmt_text.append(f"{fmt_name:<12} ", style="bold")
            m_fmt_text.append(f"{bar:<16}", style="magenta")
            m_fmt_text.append(f" {cnt} ({pct * 100:.0f}%)\n")
        self.query_one("#stats-manga-formats", Static).update(m_fmt_text)
