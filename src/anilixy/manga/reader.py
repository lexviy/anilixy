import base64
import io
import logging
import math
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from PIL import Image as PILImage
from PIL import ImageColor
from rich.segment import Segment
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen, Screen
from textual.strip import Strip
from textual.widget import Widget
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option
from textual_image._sixel import image_to_sixels
from textual_image._terminal import probe_terminal

from anilixy.anilist.api import save_manga_progress
from anilixy.core import ipc
from anilixy.manga import offline as manga_offline
from anilixy.manga.history import get_last_chapter, set_last_chapter, set_last_page
from anilixy.manga.sources import split_source_id

KITTY_START = "\x1b_G"
KITTY_END = "\x1b\\"
KITTY_CHUNK = 4096
KITTY_CLEAR = f"{KITTY_START}a=d,d=A,q=2{KITTY_END}"
SIXEL_BAND = 6
SIXEL_FRAMES_KEPT = 8
SYNC_START = "\x1b[?2026h"
SYNC_END = "\x1b[?2026l"

MIN_FRAME_INTERVAL = 0.04
ZOOM_STEP = 0.1
ZOOM_MIN = 0.5
ZOOM_MAX = 3.0
TALL_RATIO = 2.0
SCROLL_ROWS = 8
WHEEL_ROWS = 4
END_NOTICE_INTERVAL = 1.5

SPREAD_RTL = True
SPREAD_COVER_ALONE = True
FLASH_SECONDS = 3.0
KEEP_DECODED = 6
log = logging.getLogger(__name__)
USER_AGENT = {"User-Agent": "Mozilla/5.0"}


def cell_size():
    try:
        from textual_image._terminal import get_cell_size

        size = get_cell_size()
        if size.width > 0 and size.height > 0:
            return size.width, size.height
    except Exception:
        log.debug("ignored error", exc_info=True)
    return 10, 20


def terminal_graphics():
    try:
        capabilities = probe_terminal()
    except Exception:
        log.debug("ignored error", exc_info=True)
        return False, False
    return capabilities.tgp, capabilities.sixel


def use_sixel() -> bool:
    kitty, sixel = terminal_graphics()
    return sixel and not kitty


def no_graphics() -> bool:
    return not any(terminal_graphics())


class ReaderScrollbar(Widget):
    COMPONENT_CLASSES = {"reader-scrollbar--thumb", "reader-scrollbar--track"}

    DEFAULT_CSS = """
    ReaderScrollbar {
        width: 1;
        height: 100%;
        background: $background;
    }
    ReaderScrollbar > .reader-scrollbar--thumb {
        color: $primary;
    }
    ReaderScrollbar > .reader-scrollbar--track {
        color: $surface;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.thumb = None
        self._dragging = False

    def set_thumb(self, thumb) -> None:
        if thumb != self.thumb:
            self.thumb = thumb
            self.refresh()

    def render_line(self, y: int) -> Strip:
        height = self.size.height
        if self.thumb is None:
            return Strip([Segment(" ", self.rich_style)], 1)
        start, size = self.thumb
        length = max(1, round(size * height))
        top = min(round(start * height), max(0, height - length))
        if top <= y < top + length:
            style = self.get_component_rich_style("reader-scrollbar--thumb")
            return Strip([Segment("█", style)], 1)
        style = self.get_component_rich_style("reader-scrollbar--track")
        return Strip([Segment("│", style)], 1)

    def seek(self, y) -> None:
        span = max(1, self.size.height - 1)
        self.screen.seek(min(1.0, max(0.0, y / span)))

    def on_mouse_down(self, event) -> None:
        if self.thumb is None:
            return
        event.stop()
        self._dragging = True
        self.capture_mouse()
        self.seek(event.y)

    def on_mouse_move(self, event) -> None:
        if self._dragging:
            event.stop()
            self.seek(event.y)

    def on_mouse_up(self, event) -> None:
        if self._dragging:
            event.stop()
            self._dragging = False
            self.release_mouse()


class ChaptersButton(Static):
    def on_click(self) -> None:
        self.screen.action_chapter_menu()


class ChapterPickerScreen(ModalScreen):
    BINDINGS = [
        Binding("escape", "cancel", "Close"),
        Binding("down", "focus_list", "List", show=False),
    ]

    DEFAULT_CSS = """
    ChapterPickerScreen { align: center middle; background: $background 60%; }
    #chapter-picker {
        width: 60; max-width: 98%; height: 80%;
        background: $surface; border: round $primary; padding: 1 2;
    }
    #chapter-picker-list { height: 1fr; background: $surface; margin: 1 0; }
    """

    def __init__(self, labels, current) -> None:
        super().__init__()
        self.labels = labels
        self.current = current

    def compose(self) -> ComposeResult:
        with Vertical(id="chapter-picker"):
            yield Static("Chapters", classes="box-title")
            yield Input(placeholder="Filter (e.g. 12)", id="chapter-filter")
            yield OptionList(id="chapter-picker-list")
            yield Static("Enter: open  |  Tab: filter  |  Esc: close")

    def on_mount(self) -> None:
        self.fill()
        self.query_one("#chapter-picker-list", OptionList).focus()

    def fill(self, query="") -> None:
        option_list = self.query_one("#chapter-picker-list", OptionList)
        option_list.clear_options()
        query = query.lower().strip()
        options = []
        for index, label in enumerate(self.labels):
            if query and query not in label.lower():
                continue
            marker = "▶ " if index == self.current else "  "
            options.append(Option(marker + label, id=str(index)))
        option_list.add_options(options)
        ids = [option.id for option in options]
        if str(self.current) in ids:
            option_list.highlighted = ids.index(str(self.current))
        elif options:
            option_list.highlighted = 0

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "chapter-filter":
            self.fill(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.query_one("#chapter-picker-list", OptionList).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(int(event.option.id))

    def action_focus_list(self) -> None:
        self.query_one("#chapter-picker-list", OptionList).focus()

    def action_cancel(self) -> None:
        self.dismiss(None)


class DownloadOptionList(OptionList):
    BINDINGS = [
        Binding("space", "toggle", "Toggle", show=False),
        Binding("a", "toggle_all", "All", show=False),
        Binding("d", "download", "Download", show=False),
    ]

    def action_toggle(self) -> None:
        self.screen.toggle_highlighted()

    def action_toggle_all(self) -> None:
        self.screen.toggle_all()

    def action_download(self) -> None:
        self.screen.confirm()


class ChapterDownloadScreen(ModalScreen):
    BINDINGS = [
        Binding("escape", "cancel", "Close"),
        Binding("down", "focus_list", "List", show=False),
    ]

    DEFAULT_CSS = """
    ChapterDownloadScreen { align: center middle; background: $background 60%; }
    #chapter-download {
        width: 64; max-width: 98%; height: 80%;
        background: $surface; border: round $primary; padding: 1 2;
    }
    #chapter-download-list { height: 1fr; background: $surface; margin: 1 0; }
    """

    def __init__(self, labels, current, downloaded) -> None:
        super().__init__()
        self.labels = labels
        self.current = current
        self.downloaded = downloaded
        self.selected = set()
        self.shown = []

    def compose(self) -> ComposeResult:
        with Vertical(id="chapter-download"):
            yield Static("Download chapters", classes="box-title")
            yield Input(placeholder="Filter (e.g. 12)", id="chapter-download-filter")
            yield DownloadOptionList(id="chapter-download-list")
            yield Static("", id="chapter-download-hint")

    def on_mount(self) -> None:
        self.fill()
        self.query_one("#chapter-download-list", OptionList).focus()

    def prompt(self, index) -> Text:
        box = "[x]" if index in self.selected else "[ ]"
        marker = "▶" if index == self.current else " "
        saved = "  (offline)" if index in self.downloaded else ""
        return Text(f"{box} {marker} {self.labels[index]}{saved}")

    def update_hint(self) -> None:
        count = len(self.selected)
        self.query_one("#chapter-download-hint", Static).update(
            f"{count} selected  |  Space: toggle  |  A: all  |  Enter/D: download  |  Esc: close"
        )

    def fill(self, query="") -> None:
        option_list = self.query_one("#chapter-download-list", OptionList)
        option_list.clear_options()
        query = query.lower().strip()
        self.shown = [
            i for i, label in enumerate(self.labels) if not query or query in label.lower()
        ]
        option_list.add_options([Option(self.prompt(i), id=str(i)) for i in self.shown])
        if self.current in self.shown:
            option_list.highlighted = self.shown.index(self.current)
        elif self.shown:
            option_list.highlighted = 0
        self.update_hint()

    def refresh_option(self, index) -> None:
        option_list = self.query_one("#chapter-download-list", OptionList)
        option_list.replace_option_prompt(str(index), self.prompt(index))

    def toggle_highlighted(self) -> None:
        option_list = self.query_one("#chapter-download-list", OptionList)
        if option_list.highlighted is None:
            return
        index = self.shown[option_list.highlighted]
        self.selected ^= {index}
        self.refresh_option(index)
        self.update_hint()
        if option_list.highlighted < len(self.shown) - 1:
            option_list.highlighted += 1

    def toggle_all(self) -> None:
        visible = set(self.shown)
        if visible <= self.selected:
            self.selected -= visible
        else:
            self.selected |= visible
        for index in self.shown:
            self.refresh_option(index)
        self.update_hint()

    def confirm(self) -> None:
        if not self.selected:
            option_list = self.query_one("#chapter-download-list", OptionList)
            if option_list.highlighted is None:
                return
            self.selected = {self.shown[option_list.highlighted]}
        self.dismiss(sorted(self.selected))

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "chapter-download-filter":
            self.fill(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.query_one("#chapter-download-list", OptionList).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.confirm()

    def action_focus_list(self) -> None:
        self.query_one("#chapter-download-list", OptionList).focus()

    def action_cancel(self) -> None:
        self.dismiss(None)


class MangaReaderScreen(Screen):
    BINDINGS = [
        Binding("left", "prev_page", "Prev page", show=False),
        Binding("right", "next_page", "Next page", show=False),
        Binding("up", "scroll_up", "Scroll up", show=False),
        Binding("down", "scroll_down", "Scroll down", show=False),
        Binding("pageup", "page_up", "Page up", show=False),
        Binding("pagedown,space", "page_down", "Page down", show=False),
        Binding("home", "scroll_home", "Top", show=False),
        Binding("end", "scroll_end", "Bottom", show=False),
        Binding("p", "prev_chapter", "Prev chapter", show=False),
        Binding("n", "next_chapter", "Next chapter", show=False),
        Binding("c", "toggle_mode", "Toggle Webtoon"),
        Binding("w", "zoom_in", "Zoom in", show=False),
        Binding("s", "zoom_out", "Zoom out", show=False),
        Binding("0", "zoom_reset", "Reset zoom", show=False),
        Binding("d", "toggle_spread", "Two pages", show=False),
        Binding("f", "shift_pairing", "Shift pairing", show=False),
        Binding("l", "chapter_menu", "Chapters", show=False),
        Binding("o", "save_offline(1)", "Save chapter offline", show=False),
        Binding("O", "download_menu", "Choose chapters to save offline", show=False),
        Binding("escape", "back", "Quit"),
        Binding("q", "back", "Quit"),
    ]

    CSS = """
    MangaReaderScreen {
        background: $background;
        layout: vertical;
    }
    #reader-row {
        height: 1fr;
    }
    #reader {
        width: 1fr;
        height: 100%;
    }
    #status-row {
        height: 1;
    }
    #status-bar {
        width: 1fr;
        height: 1;
        background: $primary;
        color: $background;
        text-align: center;
        content-align: center middle;
        text-style: bold;
    }
    #status-bar.flash-information { background: $success; }
    #status-bar.flash-warning { background: $warning; }
    #status-bar.flash-error { background: $error; }
    #chapters-btn {
        width: 14;
        height: 1;
        background: $secondary;
        color: $background;
        text-align: center;
        text-style: bold;
    }
    #chapters-btn:hover { background: $accent; }
    """

    def __init__(self, anilist_id, source_id, title, start_chapter=None):
        super().__init__()
        self.start_chapter = start_chapter
        self.anilist_id = anilist_id
        self.source_id = str(source_id)
        source, _ = split_source_id(self.source_id)
        self.image_headers = {**USER_AGENT, **(source.image_headers if source else {})}
        self.title = title
        self.chapters = []
        self.chapter_index = 0
        self.pages = []
        self.page_index = 0

        self.zoom = 1.0
        self.mode = "page"
        self._mode_manual = False
        self._auto_checked = False
        self._y_offset = 0
        self._jump_page = None

        self.images = {}
        self._generation = 0
        self.is_loading_webtoon = False

        self._anilist_timer = None
        self._render_timer = None
        self._last_render = 0.0
        self._last_end_notice = 0.0
        self._image_id = None
        self._background = None
        self._sixel_frames = {}
        self._sixel_lock = threading.Lock()

        self._cache = {}
        self._page_cache = {}
        self._prefetch_token = 0

        self._resume = None
        self._page_timer = None
        self._loaded_index = None
        self._help_open = False

        self.spread = False

        self._offline_ids = manga_offline.downloaded_ids(self.anilist_id)
        self._spreads = {}
        self._pair_offset = 1 if SPREAD_COVER_ALONE else 0
        self._open_at_end = False
        self._dl_started = False
        self._dl_running = False
        self._current_urls = set()
        self._status_text = ""
        self._flash_until = 0.0
        self._flash_timer = None

    def compose(self) -> ComposeResult:
        with Horizontal(id="reader-row"):
            yield Static("", id="reader")
            yield ReaderScrollbar(id="scrollbar")
        with Horizontal(id="status-row"):
            yield Static("", id="status-bar")
            yield ChaptersButton("Chapters (L)", id="chapters-btn")

    def on_mount(self):
        if ipc.WINDOWS and no_graphics():
            self.notify(
                "This terminal can't show manga pages. Use Windows Terminal 1.22+ "
                "or a WezTerm nightly build.",
                severity="warning",
                timeout=15,
            )
        self.load_chapters()

    def on_resize(self, event) -> None:
        self.call_after_refresh(self.schedule_render)

    def set_status(self, text) -> None:
        self._status_text = text
        if time.monotonic() >= self._flash_until:
            self._show(text)

    def _show(self, text, level="") -> None:
        try:
            bar = self.query_one("#status-bar", Static)
        except Exception:
            return
        bar.remove_class("flash-information", "flash-warning", "flash-error")
        if level:
            bar.add_class(f"flash-{level}")
        bar.update(Text(text))

    def notify(self, message, *, title="", severity="information", timeout=None, **kwargs) -> None:
        if not self.is_attached:
            return
        duration = max(2.0, float(timeout or FLASH_SECONDS))
        text = f"{title}: {message}" if title else str(message)
        text = " ".join(text.split())[: max(10, self.size.width - 18)]
        icon = {"warning": "⚠ ", "error": "✖ "}.get(severity, "")
        self._flash_until = time.monotonic() + duration
        self._show(icon + text, severity)
        if self._flash_timer is not None:
            self._flash_timer.stop()
        self._flash_timer = self.set_timer(duration, self._end_flash)

    def _end_flash(self) -> None:
        self._flash_timer = None
        self._flash_until = 0.0
        if self.is_attached:
            self._show(self._status_text)

    @staticmethod
    def chapter_number(ch):
        raw = str(ch.get("attributes", {}).get("chapter") or "")
        match = re.search(r"(\d+(?:\.\d+)?)", raw)
        return float(match.group(1)) if match else None

    def find_chapter(self, wanted):
        try:
            wanted = float(str(wanted).strip().replace(",", "."))
        except ValueError:
            return None
        best = None
        for index, ch in enumerate(self.chapters):
            number = self.chapter_number(ch)
            if number is None:
                continue
            if number == wanted:
                return index
            if number > wanted and (best is None or number < best[0]):
                best = (number, index)
        if best is not None:
            return best[1]
        return len(self.chapters) - 1

    def chapter_label(self, index) -> str:
        attrs = self.chapters[index].get("attributes", {})
        raw = str(attrs.get("chapter") or "").strip()
        number = re.sub(r"(?i)^chapter\s*", "", raw)
        if number in ("0", "?", "None", ""):
            number = str(index + 1)
        label = f"Chapter {number}"
        title = (attrs.get("title") or "").strip()
        if title and title.lower() != raw.lower():
            label += f" · {title}"
        return label

    def fetch_chapters(self):
        source, series_url = split_source_id(self.source_id)
        chapters = []
        if source is not None:
            try:
                chapters = [
                    {
                        "id": ch.get("link"),
                        "attributes": {
                            "chapter": ch.get("name", "?"),
                            "title": ch.get("name", ""),
                        },
                    }
                    for ch in source.client.get_chapters(series_url)
                ]
            except Exception:
                log.warning("Could not load chapters for %s", self.source_id, exc_info=True)
        if chapters:
            manga_offline.remember_chapters(self.anilist_id, self.source_id, chapters)
            return chapters
        offline = manga_offline.cached_chapters(self.anilist_id, self.source_id)
        if offline:
            self.app.call_from_thread(
                self.notify, "Offline: showing saved chapters only", severity="warning"
            )
        return offline

    def fetch_pages(self, chapter_id):
        local = manga_offline.local_pages(self.anilist_id, chapter_id)
        if local:
            return local
        source, _ = split_source_id(self.source_id)
        return source.client.get_pages(chapter_id) if source else []

    def read_image_bytes(self, url) -> bytes:
        if url.startswith("file://"):
            return manga_offline.read_local(url)
        resp = requests.get(url, timeout=30, headers=self.image_headers)
        resp.raise_for_status()
        return resp.content

    def action_save_offline(self, count: int = 1) -> None:
        if not self.chapters:
            return
        start = self.chapter_index
        targets = self.chapters[start : start + max(1, int(count))]
        self.notify(f"Saving {len(targets)} chapter(s) offline...", timeout=3)
        self.save_offline(targets)

    @work(thread=True, group="offline")
    def save_offline(self, chapters) -> None:
        saved = 0
        for chapter in chapters:
            if manga_offline.is_downloaded(self.anilist_id, chapter["id"]):
                saved += 1
                continue
            try:
                pages = self.fetch_pages(chapter["id"])
            except Exception:
                pages = []
            if pages and manga_offline.download_chapter(
                self.anilist_id, self.source_id, chapter, pages,
                headers=self.image_headers, cache=self._cache,
            ):
                saved += 1
        manga_offline.remember_chapters(self.anilist_id, self.source_id, self.chapters)
        self._offline_ids = manga_offline.downloaded_ids(self.anilist_id)
        severity = "information" if saved == len(chapters) else "warning"
        self.app.call_from_thread(
            self.notify, f"Saved {saved}/{len(chapters)} chapter(s) offline", severity=severity
        )
        self.app.call_from_thread(self.update_status)

    @work(thread=True)
    def load_chapters(self):
        self.app.call_from_thread(self.set_status, "Loading chapters...")

        self.chapters = self.fetch_chapters()

        last = get_last_chapter(self.anilist_id)
        target = None
        wanted = None
        if self.start_chapter:
            try:
                wanted = float(str(self.start_chapter).strip().replace(",", "."))
            except ValueError:
                wanted = None
            if last and last.get("chapter_id") and wanted is not None:
                for i, ch in enumerate(self.chapters):
                    if ch["id"] == last["chapter_id"] and self.chapter_number(ch) == wanted:
                        target = i
                        break
            if target is None:
                target = self.find_chapter(self.start_chapter)

        if target is not None and self.chapters:
            self.chapter_index = target
            if last and last.get("chapter_id") == self.chapters[target]["id"]:
                self._resume = (last["chapter_id"], int(last.get("page") or 0))
            found = self.chapter_number(self.chapters[target])
            if found is not None and wanted is not None and found != wanted:
                self.app.call_from_thread(
                    self.notify,
                    f"Chapter {self.start_chapter} not found, opening {found:g}",
                    severity="warning",
                )
        elif last and last.get("chapter_id"):
            for i, ch in enumerate(self.chapters):
                if ch["id"] == last["chapter_id"]:
                    self.chapter_index = i
                    self._resume = (ch["id"], int(last.get("page") or 0))
                    break
        self.load_pages()

    @work(thread=True)
    def load_pages(self):
        if not self.chapters:
            self.app.call_from_thread(
                self.notify, "No chapters found", severity="warning"
            )
            self.app.call_from_thread(self.set_timer, 1.5, self.action_back)
            return

        self.app.call_from_thread(self.set_status, "Loading pages...")

        index = self.chapter_index
        ch = self.chapters[index]
        chapter_id = ch["id"]
        ch_num = ch.get("attributes", {}).get("chapter")

        pages = self._page_cache.pop(chapter_id, None)
        if pages:
            pass
        else:
            pages = self.fetch_pages(chapter_id)

        if not pages:
            self.app.call_from_thread(
                self.notify, "This chapter has no readable pages.", severity="warning"
            )
            self.app.call_from_thread(self.set_timer, 1.5, self.action_back)
            return

        self.app.call_from_thread(self.begin_chapter, pages, chapter_id, ch_num, index)

    def begin_chapter(self, pages, chapter_id, ch_num, index):
        if index != self.chapter_index:
            return
        self._generation += 1
        self.pages = pages
        self.images = {}
        self._spreads = {}
        self._pair_offset = 1 if SPREAD_COVER_ALONE else 0
        self._loaded_index = index

        self._current_urls = {p["url"] for p in pages}
        for url in list(self._cache):
            if url not in self._current_urls:
                self._cache.pop(url, None)
        self._dl_started = False
        self._dl_running = False

        resume, self._resume = self._resume, None
        at_end, self._open_at_end = self._open_at_end, False
        page = 0
        resumed = False
        if resume and resume[0] == chapter_id and 0 < resume[1] < len(pages):
            page = resume[1]
            resumed = True
        if at_end:
            page = len(pages) - 1
            resumed = False
        self.page_index = page
        self._y_offset = 0
        self._auto_checked = False
        self.is_loading_webtoon = False
        if not self._mode_manual:
            self.mode = "page"
        self._jump_page = page if (page and self.mode == "webtoon") else None
        set_last_chapter(self.anilist_id, chapter_id, ch_num, page, self.title)
        if resumed:
            self.notify(f"Resuming at page {page + 1}", timeout=3)
        if ch_num:
            self.schedule_anilist(ch_num)
        self.load_current_view()
        self.start_prefetch()
        self.app._update_rpc(self)

    def schedule_anilist(self, ch_num):
        if self._anilist_timer is not None:
            self._anilist_timer.stop()
        self._anilist_timer = self.set_timer(
            1.5, lambda c=ch_num: self.track_anilist(c)
        )

    @work(thread=True, exclusive=True)
    def track_anilist(self, chapter_name):
        if getattr(self.app, "guest", False) or not getattr(self.app, "token", None):
            return

        try:
            name_lower = str(chapter_name).lower()
            ch_int = None
            vol_int = None

            m_vol = re.search(r"(?:vol\.?|volume)\s*(\d+)", name_lower)
            if m_vol:
                vol_int = int(m_vol.group(1))

            m_ch = re.search(r"(?:chapter|ch\.?)\s*(\d+)", name_lower)
            if m_ch:
                ch_int = int(m_ch.group(1))
            else:
                numbers = re.findall(r"(\d+)", name_lower)
                if numbers:
                    ch_int = int(numbers[-1])

            if ch_int is None and vol_int is None:
                return

            result = save_manga_progress(
                self.app.token, self.anilist_id, ch_int, vol_int
            )

            if result is not None:
                msg = "AniList updated: "
                if vol_int:
                    msg += f"Vol {vol_int} "
                if ch_int:
                    msg += f"Ch {ch_int}"
                self.app.call_from_thread(self.notify, msg, timeout=2)

        except Exception as e:
            err_msg = str(e)
            if "Too Many Requests" in err_msg or "429" in err_msg:
                self.app.call_from_thread(
                    self.notify,
                    "AniList Rate Limit. Slow down!",
                    severity="warning",
                    timeout=3,
                )
            else:
                self.app.call_from_thread(
                    self.notify, f"AniList error: {e}", severity="error", timeout=5
                )

    def help_opening(self):
        self._help_open = True
        self._clear_image()

    def help_closed(self):
        self._help_open = False
        self.schedule_render()

    def schedule_page_save(self):
        if not self.pages or not self.chapters:
            return
        if self._page_timer is not None:
            self._page_timer.stop()
        self._page_timer = self.set_timer(1.5, self.save_page_now)

    def save_page_now(self):
        self._page_timer = None
        if (
            not self.pages
            or not self.chapters
            or self._loaded_index != self.chapter_index
        ):
            return
        set_last_page(
            self.anilist_id, self.chapters[self.chapter_index]["id"], self.page_index
        )

    def fetch_image(self, url):
        data = self._cache.get(url)
        if data is None:
            data = self.read_image_bytes(url)
            self._cache[url] = data
        return PILImage.open(io.BytesIO(data)).convert("RGB")

    def start_prefetch(self):
        self._prefetch_token += 1
        index = self.chapter_index + 1
        if index >= len(self.chapters):
            return
        self.prefetch_next(index, self._prefetch_token)

    @work(thread=True, group="prefetch")
    def prefetch_next(self, index, token):
        def alive():
            return token == self._prefetch_token and self.is_attached

        waited = 0.0
        while alive() and waited < 120 and (self._dl_running or self.is_loading_webtoon):
            time.sleep(0.3)
            waited += 0.3
        if not alive():
            return

        chapter = self.chapters[index]
        chapter_id = chapter["id"]
        pages = self._page_cache.get(chapter_id)
        if not pages:
            try:
                pages = self.fetch_pages(chapter_id)
            except Exception:
                return
            if not pages or not alive():
                return
            self._page_cache[chapter_id] = pages

        urls = [page["url"] for page in pages]
        keep = set(urls) | self._current_urls
        for key in list(self._page_cache):
            if key != chapter_id:
                self._page_cache.pop(key, None)
        for url in list(self._cache):
            if url not in keep:
                self._cache.pop(url, None)

        def grab(url):
            if not alive() or url in self._cache:
                return
            for _ in range(2):
                try:
                    data = self.read_image_bytes(url)
                    if alive():
                        self._cache[url] = data
                    return
                except Exception:
                    if not alive():
                        return

        with ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(grab, urls))

    def start_chapter_download(self):
        if self._dl_started or not self.pages:
            return
        self._dl_started = True
        self._dl_running = True
        self.download_chapter(self._generation, self.page_index)

    @work(thread=True, group="chapter")
    def download_chapter(self, generation, first):
        pages = self.pages
        order = list(range(first, len(pages))) + list(range(first - 1, -1, -1))

        def grab(idx):
            if generation != self._generation:
                return
            url = pages[idx]["url"]
            if url in self._cache:
                return
            for _ in range(3):
                try:
                    data = self.read_image_bytes(url)
                    if generation == self._generation:
                        self._cache[url] = data
                    break
                except Exception:
                    if generation != self._generation:
                        return
            self.app.call_from_thread(self.on_chapter_progress, generation)

        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(grab, order))
        self.app.call_from_thread(self.chapter_downloaded, generation)

    def on_chapter_progress(self, generation):
        if generation == self._generation:
            self.update_status()

    def chapter_downloaded(self, generation):
        if generation != self._generation:
            return
        self._dl_running = False
        self.update_status()

    def decode_ahead(self):
        if self.mode != "page" or not self.pages:
            return
        for key in list(self.images):
            if abs(key - self.page_index) > KEEP_DECODED:
                self.images.pop(key, None)
        ahead = 4 if self.spread else 2
        wanted = [
            i
            for i in range(self.page_index + 1, self.page_index + 1 + ahead)
            if i < len(self.pages) and i not in self.images
        ]
        if wanted:
            self.decode_pages(wanted, self._generation, self.images)

    @work(thread=True, group="decode")
    def decode_pages(self, wanted, generation, images):
        for idx in wanted:
            if generation != self._generation:
                return
            url = self.pages[idx]["url"]
            if url not in self._cache:
                continue
            try:
                images[idx] = self.fetch_image(url)
            except Exception:
                log.debug("ignored error", exc_info=True)
        if generation == self._generation and use_sixel():
            self.app.call_from_thread(self.schedule_sixel_ahead)

    def group_start(self, page):
        if self._pair_offset == 1 and page == 0:
            return 0
        return page - ((page - self._pair_offset) % 2)

    def visible_pages(self, start=None):
        if start is None:
            start = self.page_index
        if self.mode == "page" and self.spread:
            if (self._pair_offset == 1 and start == 0) or start + 1 >= len(self.pages):
                return [start]
            return [start, start + 1]
        return [start]

    def load_current_view(self):
        if self.mode == "page" and self.spread and self.pages:
            self.page_index = self.group_start(self.page_index)
        self.update_status()
        self.schedule_page_save()
        if self.mode == "page":
            self.start_chapter_download()
            missing = [i for i in self.visible_pages() if i not in self.images]
            if missing:
                self.set_status("Loading image...")
                for i in missing:
                    self.download_image(i, self._generation, self.images)
            else:
                self.schedule_render()
                self.decode_ahead()
        else:
            if not self.is_loading_webtoon and len(self.images) < len(self.pages):
                self.is_loading_webtoon = True
                self.download_webtoon_images(self._generation, self.images)
            self.schedule_render()

    @work(thread=True)
    def download_image(self, page_idx, generation, images):
        try:
            img = self.fetch_image(self.pages[page_idx]["url"])
        except Exception as e:
            if generation == self._generation:
                self.app.call_from_thread(
                    self.notify, f"Error loading page: {e}", severity="error"
                )
            return
        images[page_idx] = img
        if generation == self._generation:
            self.app.call_from_thread(self.on_image_ready, page_idx)

    @work(thread=True)
    def download_webtoon_images(self, generation, images):
        def fetch(page_idx):
            if generation != self._generation:
                return page_idx, None
            if page_idx in images:
                return page_idx, images[page_idx]
            url = self.pages[page_idx]["url"]
            for _ in range(2):
                try:
                    return page_idx, self.fetch_image(url)
                except Exception:
                    if generation != self._generation:
                        break
            return page_idx, None

        failed = 0
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(fetch, i) for i in range(len(self.pages))]
            for future in as_completed(futures):
                idx, img = future.result()
                if generation != self._generation:
                    continue
                if img is None:
                    failed += 1
                    img = PILImage.new("RGB", (800, 300), (40, 40, 40))
                images[idx] = img
                self.app.call_from_thread(self.on_webtoon_progress, generation)

        if generation == self._generation:
            self.app.call_from_thread(self.finish_webtoon_loading, generation, failed)

    def on_image_ready(self, page_idx):
        img = self.images.get(page_idx)
        if (
            img is not None
            and page_idx == self.page_index
            and self.mode == "page"
            and not self._mode_manual
            and not self._auto_checked
        ):
            self._auto_checked = True
            if img.height > TALL_RATIO * img.width:
                self.mode = "webtoon"
                self._jump_page = self.page_index or None
                self.notify("Webtoon mode (press C to switch)", timeout=3)
                self.load_current_view()
                return
        self.schedule_render()
        self.update_status()
        self.decode_ahead()

    def on_webtoon_progress(self, generation):
        if generation != self._generation:
            return
        self.schedule_render()
        self.update_status()

    def finish_webtoon_loading(self, generation, failed):
        if generation != self._generation:
            return
        self.is_loading_webtoon = False
        if failed:
            self.notify(f"{failed} page(s) failed to load", severity="warning")
        self.schedule_render()
        self.update_status()

    def schedule_render(self):
        if self._render_timer is not None:
            return
        wait = self._last_render + MIN_FRAME_INTERVAL - time.monotonic()
        self._render_timer = self.set_timer(max(wait, 0.001), self._run_render)

    def _run_render(self):
        self._render_timer = None
        try:
            self.render_kitty()
        finally:
            self._last_render = time.monotonic()

    def view_geometry(self):
        reader = self.query_one("#reader", Static)
        cols, rows = reader.size.width, reader.size.height
        if cols == 0 or rows == 0:
            return None
        cell_w, cell_h = cell_size()
        return cols, rows, cell_w, cell_h, reader.region.x, reader.region.y

    def scale_for(self, img, sw, sh, zoom=None):
        zoom = self.zoom if zoom is None else zoom
        if self.mode == "page":
            base = min(sw / img.width, sh / img.height)
        else:
            base = min(img.width, sw) / img.width
        return min(base * zoom, sw / img.width)

    def _image_for(self, key):
        if isinstance(key, tuple):
            return self._spreads.get(key)
        return self.images.get(key)

    def spread_image(self, a, b):
        key = ("spread", a, b)
        cached = self._spreads.get(key)
        if cached is not None:
            return key, cached
        first, second = self.images.get(a), self.images.get(b)
        if first is None or second is None:
            return key, None
        left, right = (second, first) if SPREAD_RTL else (first, second)
        height = max(left.height, right.height)

        def fit(img):
            if img.height == height:
                return img
            width = max(1, round(img.width * height / img.height))
            return img.resize((width, height), PILImage.Resampling.LANCZOS)

        left, right = fit(left), fit(right)
        canvas = PILImage.new(
            "RGB", (left.width + right.width, height), self.background_rgb()
        )
        canvas.paste(left, (0, 0))
        canvas.paste(right, (left.width, 0))
        if len(self._spreads) >= 4:
            self._spreads.clear()
        self._spreads[key] = canvas
        return key, canvas

    def page_layout(self, sw, sh, pages=None):
        items = []
        if self.mode == "page":
            pages = pages or self.visible_pages()
            if len(pages) == 2:
                key, img = self.spread_image(*pages)
            else:
                key, img = pages[0], self.images.get(pages[0])
            if img is not None:
                scale = self.scale_for(img, sw, sh)
                items.append(
                    (
                        key,
                        0,
                        max(1, round(img.width * scale)),
                        max(1, round(img.height * scale)),
                    )
                )
            return items
        top = 0
        for idx in range(len(self.pages)):
            img = self.images.get(idx)
            if img is None:
                break
            scale = self.scale_for(img, sw, sh)
            w = max(1, round(img.width * scale))
            h = max(1, round(img.height * scale))
            items.append((idx, top, w, h))
            top += h
        return items

    @staticmethod
    def total_height(items):
        return items[-1][1] + items[-1][3] if items else 0

    def background_rgb(self):
        theme = self.app.theme
        if self._background is None or self._background[0] != theme:
            try:
                rgb = ImageColor.getrgb(
                    self.app.get_css_variables().get("background", "#000000")
                )
            except Exception:
                rgb = (0, 0, 0)
            self._background = (theme, rgb)
        return self._background[1]

    def build_frame(self, items, offset, sw, sh, cell_w):
        total = self.total_height(items)
        content_w = max(item[2] for item in items)
        canvas_w = min(sw, math.ceil(content_w / cell_w) * cell_w)
        canvas = PILImage.new("RGB", (canvas_w, sh), self.background_rgb())
        shift = (sh - total) // 2 if total < sh else 0

        for idx, top, w, h in items:
            screen_y = top - offset + shift
            if screen_y + h <= 0 or screen_y >= sh:
                continue
            src = self._image_for(idx)
            ratio = h / src.height
            visible_top = max(0, -screen_y)
            visible_bottom = min(h, sh - screen_y)
            src0 = min(src.height - 1, int(visible_top / ratio))
            src1 = min(src.height, int(math.ceil(visible_bottom / ratio)))
            if src1 <= src0:
                continue
            dst0 = round(src0 * ratio)
            dst1 = min(h, round(src1 * ratio))
            if dst1 <= dst0:
                continue
            piece = src.crop((0, src0, src.width, src1))
            size = (w, dst1 - dst0)
            if piece.size != size:
                downscale = size[0] < piece.width or size[1] < piece.height
                resample = (
                    PILImage.Resampling.LANCZOS
                    if downscale
                    else PILImage.Resampling.BICUBIC
                )
                piece = piece.resize(size, resample)
            canvas.paste(piece, ((canvas_w - w) // 2, screen_y + dst0))
        return canvas

    def encode_sixel(self, canvas, sw):
        height = canvas.height - canvas.height % SIXEL_BAND
        frame = PILImage.new("RGB", (sw, height), self.background_rgb())
        frame.paste(canvas, ((sw - canvas.width) // 2, 0))
        return image_to_sixels(frame)

    def sixel_key(self, pages, sw, sh, offset):
        return (
            self._generation,
            tuple(pages),
            self.mode,
            self.spread,
            self.zoom,
            sw,
            sh,
            offset,
            self.background_rgb(),
        )

    def keep_sixel(self, key, data):
        with self._sixel_lock:
            self._sixel_frames[key] = data
            while len(self._sixel_frames) > SIXEL_FRAMES_KEPT:
                self._sixel_frames.pop(next(iter(self._sixel_frames)))

    def draw_sixel(self, items, offset, sw, sh, cell_w, reader_x, reader_y):
        key = self.sixel_key(self.visible_pages(), sw, sh, offset)
        cached = self.mode == "page"
        data = self._sixel_frames.get(key) if cached else None
        if data is None:
            data = self.encode_sixel(self.build_frame(items, offset, sw, sh, cell_w), sw)
            if cached:
                self.keep_sixel(key, data)
        self._tty_write(
            f"{SYNC_START}\x1b7\x1b[{reader_y + 1};{reader_x + 1}H{data}\x1b8{SYNC_END}"
        )
        if cached:
            self.encode_neighbours(sw, sh, cell_w)

    def schedule_sixel_ahead(self):
        geo = self.view_geometry() if self.is_attached else None
        if geo is not None and self.mode == "page":
            cols, rows, cell_w, cell_h, _, _ = geo
            self.encode_neighbours(cols * cell_w, rows * cell_h, cell_w)

    @work(thread=True, exclusive=True, group="sixel")
    def encode_neighbours(self, sw, sh, cell_w):
        generation = self._generation
        shown = self.visible_pages()
        for start in (shown[-1] + 1, shown[0] - len(shown)):
            if generation != self._generation or self.mode != "page":
                return
            if not 0 <= start < len(self.pages):
                continue
            pages = self.visible_pages(start)
            key = self.sixel_key(pages, sw, sh, 0)
            items = self.page_layout(sw, sh, pages)
            if key in self._sixel_frames or not items:
                continue
            try:
                self.keep_sixel(key, self.encode_sixel(self.build_frame(items, 0, sw, sh, cell_w), sw))
            except Exception:
                log.debug("ignored error", exc_info=True)

    def send_frame(self, canvas, cols, rows, cell_w, reader_x, reader_y):
        width, height = canvas.size
        canvas_cols = width // cell_w
        x = reader_x + (cols - canvas_cols) // 2 + 1
        y = reader_y + 1
        data = base64.b64encode(canvas.tobytes()).decode("ascii")
        new_id = 1 if self._image_id != 1 else 2

        parts = [f"\x1b[{y};{x}H"]
        for i in range(0, len(data), KITTY_CHUNK):
            chunk = data[i : i + KITTY_CHUNK]
            more = 1 if i + KITTY_CHUNK < len(data) else 0
            if i == 0:
                control = (
                    f"a=T,f=24,s={width},v={height},c={canvas_cols},r={rows},"
                    f"i={new_id},C=1,m={more},q=2"
                )
            else:
                control = f"m={more}"
            parts.append(f"{KITTY_START}{control};{chunk}{KITTY_END}")
        if self._image_id is not None:
            parts.append(f"{KITTY_START}a=d,d=I,i={self._image_id},q=2{KITTY_END}")

        self._tty_write("".join(parts))
        self._image_id = new_id

    def _tty_write(self, data: str) -> None:
        driver = getattr(self.app, "_driver", None)
        if driver is not None:
            try:
                driver.write(data)
                return
            except Exception:
                log.debug("ignored error", exc_info=True)
        try:
            fd = os.open("/dev/tty", os.O_WRONLY)
        except OSError:
            return
        try:
            view = memoryview(data.encode("ascii", "ignore"))
            while view:
                view = view[os.write(fd, view) :]
        finally:
            os.close(fd)

    def _clear_image(self):
        if use_sixel():
            self.query_one("#reader", Static).refresh()
        else:
            self._tty_write(KITTY_CLEAR)
        self._image_id = None
        try:
            self.query_one("#scrollbar", ReaderScrollbar).set_thumb(None)
        except Exception:
            log.debug("ignored error", exc_info=True)

    def render_kitty(self):
        if not self.is_attached or self._help_open:
            return
        geo = self.view_geometry()
        if geo is None:
            return
        cols, rows, cell_w, cell_h, reader_x, reader_y = geo
        sw, sh = cols * cell_w, rows * cell_h

        items = self.page_layout(sw, sh)
        if not items:
            self.query_one("#scrollbar", ReaderScrollbar).set_thumb(None)
            return
        total = self.total_height(items)

        if self.mode == "webtoon" and self._jump_page is not None:
            if len(items) <= self._jump_page:
                return
            self._y_offset = items[self._jump_page][1]
            self._jump_page = None

        self._y_offset = min(max(0, self._y_offset), max(0, total - sh))
        offset = int(round(self._y_offset))

        try:
            if use_sixel():
                self.draw_sixel(items, offset, sw, sh, cell_w, reader_x, reader_y)
            else:
                canvas = self.build_frame(items, offset, sw, sh, cell_w)
                self.send_frame(canvas, cols, rows, cell_w, reader_x, reader_y)
        except Exception as e:
            self.notify(f"Error drawing image: {e}", severity="error")
            return

        thumb = None
        if total > sh:
            thumb = (offset / total, sh / total)
        self.query_one("#scrollbar", ReaderScrollbar).set_thumb(thumb)

        if self.mode == "webtoon":
            center = offset + sh / 2
            for idx, top, _w, h in items:
                if top <= center < top + h:
                    if idx != self.page_index:
                        self.page_index = idx
                        self.update_status()
                        self.schedule_page_save()
                    break

    def rpc_progress(self):
        if not self.chapters:
            return None
        ch = self.chapters[self.chapter_index]
        ch_str = str(ch.get("attributes", {}).get("chapter") or "?").strip()
        ch_str = re.sub(r"(?i)^chapter\s*", "", ch_str)
        if ch_str in ("0", "?", "None", ""):
            ch_str = str(self.chapter_index + 1)
        return f"Chapter {ch_str} ({self.chapter_index + 1}/{len(self.chapters)})"

    def update_status(self):
        if not self.chapters or not self.pages:
            return
        ch = self.chapters[self.chapter_index]

        raw_ch_num = ch.get("attributes", {}).get("chapter") or "?"
        ch_str = re.sub(r"(?i)^chapter\s*", "", str(raw_ch_num).strip())
        if ch_str in ("0", "?", "None", ""):
            ch_str = str(self.chapter_index + 1)

        total_ch = len(self.chapters)
        zoom_str = f"{round(self.zoom * 100)}%"

        shown = self.visible_pages()
        two = self.mode == "page" and self.spread and len(shown) == 2
        page_str = f"{shown[0] + 1}-{shown[1] + 1}" if two else str(self.page_index + 1)
        mode_str = "Webtoon" if self.mode == "webtoon" else ("Spread" if self.spread else "Page")

        loading = ""
        if self.mode == "webtoon" and self.is_loading_webtoon:
            loading = f"| Loading {len(self.images)}/{len(self.pages)} "
        elif self._dl_running:
            got = sum(1 for u in self._current_urls if u in self._cache)
            loading = f"| Downloaded {got}/{len(self.pages)} "

        title = self.title or ""
        if len(title) > 30:
            title = title[:29] + "…"
        title = f" {title} |" if title else ""
        offline = " [offline]" if ch["id"] in self._offline_ids else ""
        self.set_status(
            f"{title} Ch {ch_str}{offline} ({self.chapter_index + 1}/{total_ch}) "
            f"| Page {page_str}/{len(self.pages)} {loading}"
            f"| {mode_str} (C/D) | Zoom {zoom_str} | ? Help "
        )

    def action_toggle_mode(self):
        if not self.pages:
            return
        self._mode_manual = True
        if self.mode == "page":
            self.mode = "webtoon"
            self._jump_page = self.page_index
        else:
            self.mode = "page"
            self._jump_page = None
        self._y_offset = 0
        self._clear_image()
        self.load_current_view()
        self.notify(f"Mode: {self.mode.capitalize()}")

    def change_zoom(self, value):
        value = round(min(ZOOM_MAX, max(ZOOM_MIN, value)), 1)
        if value == self.zoom:
            return
        geo = self.view_geometry()
        if geo is None:
            self.zoom = value
            self.update_status()
            return
        cols, rows, cell_w, cell_h = geo[:4]
        sw, sh = cols * cell_w, rows * cell_h

        before = self.page_layout(sw, sh)
        if value > self.zoom and before:
            ref = self.images.get(self.page_index) if self.mode == "webtoon" else None
            ref = ref or self._image_for(before[0][0])
            if self.scale_for(ref, sw, sh, value) <= self.scale_for(ref, sw, sh):
                self.notify("Maximum zoom for this width", timeout=2)
                return
        total_before = self.total_height(before)
        anchor = (self._y_offset + sh / 2) / total_before if total_before else 0

        self.zoom = value
        total_after = self.total_height(self.page_layout(sw, sh))
        self._y_offset = max(0, anchor * total_after - sh / 2)
        self.schedule_render()
        self.update_status()

    def action_zoom_in(self):
        self.change_zoom(self.zoom + ZOOM_STEP)

    def action_zoom_out(self):
        self.change_zoom(self.zoom - ZOOM_STEP)

    def action_zoom_reset(self):
        self.change_zoom(1.0)

    def scroll_limits(self):
        geo = self.view_geometry()
        if geo is None:
            return None
        cols, rows, cell_w, cell_h = geo[:4]
        sw, sh = cols * cell_w, rows * cell_h
        items = self.page_layout(sw, sh)
        if not items:
            return None
        return items, sh, cell_h, max(0, self.total_height(items) - sh)

    def scroll_view(self, delta):
        limits = self.scroll_limits()
        if limits is None or self._jump_page is not None:
            return
        items, sh, cell_h, max_offset = limits
        target = min(max(0, self._y_offset + delta), max_offset)
        if target == self._y_offset:
            if (
                delta > 0
                and self.mode == "webtoon"
                and not self.is_loading_webtoon
                and time.monotonic() - self._last_end_notice > END_NOTICE_INTERVAL
            ):
                self._last_end_notice = time.monotonic()
                self.notify("End of chapter. Press N for next chapter", timeout=2)
            return
        self._y_offset = target
        self.schedule_render()

    def step_pixels(self, rows):
        return rows * cell_size()[1]

    def action_scroll_up(self):
        self.scroll_view(-self.step_pixels(SCROLL_ROWS))

    def action_scroll_down(self):
        self.scroll_view(self.step_pixels(SCROLL_ROWS))

    def action_page_up(self):
        limits = self.scroll_limits()
        if limits:
            self.scroll_view(-int(limits[1] * 0.9))

    def action_page_down(self):
        limits = self.scroll_limits()
        if limits:
            self.scroll_view(int(limits[1] * 0.9))

    def action_scroll_home(self):
        self.scroll_view(-self._y_offset)

    def action_scroll_end(self):
        limits = self.scroll_limits()
        if limits:
            self.scroll_view(limits[3] - self._y_offset)

    def on_mouse_scroll_down(self, event) -> None:
        event.stop()
        self.scroll_view(self.step_pixels(WHEEL_ROWS))

    def on_mouse_scroll_up(self, event) -> None:
        event.stop()
        self.scroll_view(-self.step_pixels(WHEEL_ROWS))

    def seek(self, fraction):
        limits = self.scroll_limits()
        if limits is None or self._jump_page is not None:
            return
        self._y_offset = fraction * limits[3]
        self.schedule_render()

    def flip_page(self, direction):
        if self.mode == "page":
            if self.spread:
                start = self.group_start(self.page_index)
                cover = self._pair_offset == 1 and start == 0
                if direction > 0:
                    target = start + (1 if cover else 2)
                else:
                    target = 0 if (self._pair_offset == 1 and start == 1) else start - 2
            else:
                target = self.page_index + direction
            if direction > 0 and target >= len(self.pages):
                self.action_next_chapter()
                return
            if direction < 0 and target < 0:
                if self.chapter_index > 0:
                    self._open_at_end = True
                self.action_prev_chapter()
                return
            self.page_index = target
            self._y_offset = 0
            self.load_current_view()
            return

        limits = self.scroll_limits()
        if limits is None:
            return
        items, sh, cell_h, max_offset = limits
        tops = [item[1] for item in items]
        if direction > 0:
            ahead = [top for top in tops if top > self._y_offset + 1]
            if not ahead:
                self.action_next_chapter()
                return
            target = ahead[0]
        else:
            behind = [top for top in tops if top < self._y_offset - 1]
            if not behind and self._y_offset <= 1:
                if self.chapter_index > 0:
                    self._open_at_end = True
                    self.action_prev_chapter()
                else:
                    self.notify("First page", severity="warning")
                return
            target = behind[-1] if behind else 0
        self._y_offset = min(target, max_offset)
        self.schedule_render()

    def action_toggle_spread(self):
        if not self.pages:
            return
        if self.mode != "page":
            self.notify("Two pages only works in page mode (press C)", severity="warning")
            return
        self.spread = not self.spread
        self._spreads.clear()
        self._y_offset = 0
        self.load_current_view()
        self.notify("Two pages: on" if self.spread else "Two pages: off", timeout=2)

    def action_shift_pairing(self):
        if not self.pages:
            return
        if not (self.mode == "page" and self.spread):
            self.notify("Turn on two pages first (D)", severity="warning")
            return
        start = self.group_start(self.page_index)
        new = start + 1 if start + 1 < len(self.pages) else start - 1
        new = max(0, new)
        self._pair_offset = new % 2
        self.page_index = new
        self._spreads.clear()
        self._y_offset = 0
        self.load_current_view()

    def action_chapter_menu(self):
        if not self.chapters or self._help_open:
            return
        labels = [self.chapter_label(i) for i in range(len(self.chapters))]
        self.help_opening()

        def closed(index) -> None:
            self.help_closed()
            if index is not None and index != self.chapter_index:
                self.go_to_chapter(index)

        self.app.push_screen(ChapterPickerScreen(labels, self.chapter_index), closed)

    def action_download_menu(self):
        if not self.chapters or self._help_open:
            return
        labels = [self.chapter_label(i) for i in range(len(self.chapters))]
        downloaded = {
            i for i, ch in enumerate(self.chapters) if ch["id"] in self._offline_ids
        }
        self.help_opening()

        def closed(indices) -> None:
            self.help_closed()
            if not indices:
                return
            targets = [self.chapters[i] for i in indices]
            self.notify(f"Saving {len(targets)} chapter(s) offline...", timeout=3)
            self.save_offline(targets)

        self.app.push_screen(
            ChapterDownloadScreen(labels, self.chapter_index, downloaded), closed
        )

    def go_to_chapter(self, index):
        self.chapter_index = index
        self._resume = None
        self.load_pages()

    def action_prev_page(self):
        self.flip_page(-1)

    def action_next_page(self):
        self.flip_page(1)

    def action_prev_chapter(self):
        if self.chapter_index > 0:
            self.chapter_index -= 1
            self.load_pages()
        else:
            self.notify("First chapter", severity="warning")

    def action_next_chapter(self):
        if self.chapter_index < len(self.chapters) - 1:
            self.chapter_index += 1
            self.load_pages()
        else:
            self.notify("Last chapter", severity="warning")

    def action_back(self):
        if self._page_timer is not None:
            self._page_timer.stop()
        self.save_page_now()
        self._generation += 1
        self._prefetch_token += 1
        self._cache.clear()
        self._page_cache.clear()
        self._clear_image()
        self.app.pop_screen()
