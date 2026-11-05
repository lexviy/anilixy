import asyncio
import io
import logging
import math
import posixpath
import re
import threading
from collections import Counter
from pathlib import Path
from urllib.parse import unquote

import ebooklib
from bs4 import BeautifulSoup
from bs4.element import NavigableString, PreformattedString
from ebooklib import epub
from PIL import Image as PILImage
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Static
from textual_image.widget import Image as TextualImage

from anilixy.anilist.api import save_manga_progress
from anilixy.manga.reader import ChapterPickerScreen
from anilixy.novels.reading import (
    base_for,
    counted,
    get_novel_state,
    pick_volume,
    save_novel_state,
)
from anilixy.ui.picker import fzf_available, pick_path

log = logging.getLogger(__name__)


BLOCK_TAGS = {
    "html",
    "body",
    "p",
    "div",
    "section",
    "article",
    "aside",
    "blockquote",
    "li",
    "ul",
    "ol",
    "dl",
    "dt",
    "dd",
    "table",
    "tr",
    "td",
    "th",
    "pre",
    "hr",
    "figure",
    "figcaption",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
}
SKIP_TAGS = {"script", "style", "head", "title"}
IMAGE_TAGS = {"img", "image"}

SENTENCE_END = (".", "!", "?", "…", '"', "”", "’", "'", ")", "]", "」", "』")
PAGE_NUMBER = re.compile(r"^(page\s*)?\d{1,4}$", re.IGNORECASE)
HEADING = re.compile(
    r"^(chapter|prologue|epilogue|interlude|intermission|afterword|side story|short story|final chapter)\b",
    re.IGNORECASE,
)
PAGES_PER_CHAPTER = 10
MARGIN = 0.06
MIN_IMAGE_AREA = 100 * 100
RENDER_DPI = 110

MAX_IMAGE_SIZE = (1400, 2000)
KEEP_RADIUS = 1
ZOOM_MIN = 0.2
ZOOM_MAX = 1.0
ZOOM_STEP = 0.1


NUMBER = (
    r"(?:\d+|[ivxlc]{1,6}|one|two|three|four|five|six|seven|eight|nine|ten|eleven"
    r"|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty)"
)
CHAPTER_TITLE = re.compile(
    rf"^\s*(?:(?:chapter|chap\.?|ch\.?|episode|capítulo|capitulo|cap\.?)\s*{NUMBER}\b"
    r"|第\s*\d+\s*章|\d{1,3}\b)",
    re.IGNORECASE,
)
LEAD_IN = re.compile(
    r"^\s*(prologue|foreword|preface|prelude|opening|introduction)\b", re.IGNORECASE
)


def detect_chapter_runs(source):
    flags = []
    for index in range(len(source.chapters)):
        try:
            title = source.chapter_title(index) or ""
        except Exception:
            title = ""
        flags.append(bool(CHAPTER_TITLE.match(title)))
    runs = []
    i = 0
    while i < len(flags):
        if flags[i]:
            j = i
            while j + 1 < len(flags) and flags[j + 1]:
                j += 1
            runs.append([i, j])
            i = j + 1
        else:
            i += 1
    return runs


def lead_in_index(source, runs):
    if not runs:
        return None
    i = runs[0][0]
    while i > 0 and LEAD_IN.match(source.chapter_title(i - 1) or ""):
        i -= 1
    return i


def cell_size():
    try:
        from textual_image._terminal import get_cell_size

        size = get_cell_size()
        if size.width > 0 and size.height > 0:
            return size.width, size.height
    except Exception:
        log.debug("ignored error", exc_info=True)
    return 10, 20


def decode_image(data):
    try:
        image = PILImage.open(io.BytesIO(data))
        image.load()
        image = image.convert("RGB")
        image.thumbnail(MAX_IMAGE_SIZE, PILImage.Resampling.LANCZOS)
        return image
    except Exception:
        return None


def extract_blocks(html, resolve_image):
    soup = BeautifulSoup(html, "html.parser")
    blocks = []
    paragraphs = []
    buffer = []

    def flush():
        text = re.sub(r" *\n *", "\n", "".join(buffer)).strip()
        buffer.clear()
        if text:
            paragraphs.append(text)

    def close_text():
        flush()
        if paragraphs:
            blocks.append({"type": "text", "content": "\n\n".join(paragraphs)})
            paragraphs.clear()

    def walk(node):
        for child in node.children:
            if isinstance(child, NavigableString):
                if not isinstance(child, PreformattedString):
                    buffer.append(re.sub(r"\s+", " ", str(child)))
            elif child.name in SKIP_TAGS:
                continue
            elif child.name in IMAGE_TAGS:
                source = (
                    child.get("src") or child.get("xlink:href") or child.get("href")
                )
                data = resolve_image(source)
                if data:
                    close_text()
                    blocks.append({"type": "image", "content": data})
            elif child.name == "br":
                buffer.append("\n")
            elif child.name in BLOCK_TAGS:
                flush()
                walk(child)
                flush()
            else:
                walk(child)

    walk(soup)
    close_text()
    return blocks


class BookError(Exception):
    pass


class TolerantEpubReader(epub.EpubReader):
    def read_file(self, name):
        try:
            return super().read_file(name)
        except KeyError:
            return b""


class EpubSource:
    kind = "EPUB"

    def __init__(self, data):
        try:
            reader = TolerantEpubReader(io.BytesIO(data), {"ignore_ncx": True})
            book = reader.load()
            reader.process()
            self.images = {}
            for item in book.get_items():
                media = (getattr(item, "media_type", "") or "").lower()
                if item.get_type() in (
                    ebooklib.ITEM_IMAGE,
                    ebooklib.ITEM_COVER,
                ) or media.startswith("image/"):
                    name = item.get_name()
                    content = item.get_content()
                    if not content:
                        continue
                    self.images[name] = content
                    self.images.setdefault(posixpath.basename(name), content)
            self.chapters = self.spine_documents(book)
            self.titles = self.toc_titles(book)
            self._headings = {}
        except Exception as error:
            raise BookError(f"Could not read the EPUB: {error}") from error

    @staticmethod
    def spine_documents(book):
        items = {item.get_id(): item for item in book.get_items()}
        ordered = []
        seen = set()
        for entry in book.spine:
            idref = entry[0] if isinstance(entry, (tuple, list)) else entry
            item = items.get(idref)
            if (
                item is not None
                and idref not in seen
                and item.get_type() == ebooklib.ITEM_DOCUMENT
                and not isinstance(item, epub.EpubNav)
                and item.get_content()
            ):
                ordered.append(item)
                seen.add(idref)
        if ordered:
            return ordered
        return [
            item
            for item in book.get_items()
            if item.get_type() == ebooklib.ITEM_DOCUMENT
            and not isinstance(item, epub.EpubNav)
            and item.get_content()
        ]

    @staticmethod
    def toc_titles(book):
        titles = {}

        def walk(nodes):
            for node in nodes:
                if isinstance(node, (tuple, list)):
                    walk([node[0]])
                    if len(node) > 1:
                        walk(node[1])
                    continue
                href = getattr(node, "href", None)
                title = getattr(node, "title", None)
                if href and title:
                    key = posixpath.basename(unquote(href.split("#")[0]))
                    titles.setdefault(key, re.sub(r"\s+", " ", title).strip())

        try:
            walk(book.toc)
        except Exception:
            log.debug("ignored error", exc_info=True)
        return titles

    def heading(self, index):
        if index not in self._headings:
            text = ""
            try:
                soup = BeautifulSoup(self.chapters[index].get_content(), "html.parser")
                root = soup.body or soup
                tag = root.find(["h1", "h2", "h3", "h4"])
                if tag is not None:
                    text = tag.get_text(" ", strip=True)
                if not text:
                    text = next(iter(root.stripped_strings), "")
            except Exception:
                text = ""
            self._headings[index] = re.sub(r"\s+", " ", text).strip()[:80]
        return self._headings[index]

    def chapter_title(self, index):
        item = self.chapters[index]
        title = self.titles.get(posixpath.basename(item.get_name()))
        return title or self.heading(index)

    def resolve_image(self, source, document_name):
        if not source:
            return None
        source = unquote(source.split("#")[0].split("?")[0]).strip()
        if not source:
            return None
        base = posixpath.dirname(document_name)
        resolved = posixpath.normpath(posixpath.join(base, source)).lstrip("/\\")
        return (
            self.images.get(resolved)
            or self.images.get(source.lstrip("/"))
            or self.images.get(posixpath.basename(source))
        )

    def blocks(self, index):
        item = self.chapters[index]
        name = item.get_name()
        raw = extract_blocks(
            item.get_content(), lambda source: self.resolve_image(source, name)
        )
        prepared = []
        for block in raw:
            if block["type"] == "text":
                prepared.append(block)
                continue
            image = decode_image(block["content"])
            if image is not None:
                prepared.append({"type": "image", "image": image})
        return prepared


def block_paragraphs(block):
    lines = []
    for line in block.get("lines", []):
        text = "".join(span["text"] for span in line["spans"]).strip()
        if text:
            lines.append((text, line["bbox"]))
    if not lines:
        return []

    left = min(bbox[0] for _, bbox in lines)
    paragraphs = []
    current = ""
    previous_bottom = None
    for text, bbox in lines:
        height = max(1.0, bbox[3] - bbox[1])
        indented = bbox[0] - left > 0.6 * height
        spaced = (
            previous_bottom is not None and bbox[1] - previous_bottom > 0.5 * height
        )
        if current and (indented or spaced):
            paragraphs.append(current)
            current = text
        elif not current:
            current = text
        elif current.endswith("-") and text[:1].islower():
            current = current[:-1] + text
        else:
            current += " " + text
        previous_bottom = bbox[3]
    if current:
        paragraphs.append(current)
    cleaned = (re.sub(r"\s+", " ", paragraph).strip() for paragraph in paragraphs)
    return [paragraph for paragraph in cleaned if paragraph]


def join_paragraphs(previous, following):
    if previous.endswith("-") and following[:1].islower():
        return previous[:-1] + following
    return previous + " " + following


class PdfSource:
    kind = "PDF"

    def __init__(self, data):
        try:
            import pymupdf
        except ImportError:
            try:
                import fitz as pymupdf
            except ImportError as error:
                raise BookError(
                    "PDF support needs PyMuPDF (pipx inject anilixy pymupdf)"
                ) from error
        self.pymupdf = pymupdf
        try:
            self.doc = pymupdf.open(stream=data, filetype="pdf")
        except Exception as error:
            raise BookError(f"Could not open the PDF: {error}") from error
        if self.doc.needs_pass:
            raise BookError("This PDF is password protected")
        if self.doc.page_count == 0:
            raise BookError("This PDF has no pages")
        self.lock = threading.Lock()
        self.chapters = self.split_chapters()

    def chapter_title(self, index):
        return self.chapters[index]["title"]

    def split_chapters(self):
        count = self.doc.page_count
        starts = self.toc_starts() or self.heading_starts()
        if not starts:
            return [
                {
                    "title": f"Pages {start + 1}-{min(start + PAGES_PER_CHAPTER, count)}",
                    "start": start,
                    "end": min(start + PAGES_PER_CHAPTER, count),
                }
                for start in range(0, count, PAGES_PER_CHAPTER)
            ]
        chapters = []
        if starts[0][1] > 0:
            chapters.append({"title": "Front matter", "start": 0, "end": starts[0][1]})
        for position, (title, page) in enumerate(starts):
            end = starts[position + 1][1] if position + 1 < len(starts) else count
            chapters.append({"title": title, "start": page, "end": end})
        return chapters

    def toc_starts(self):
        try:
            toc = self.doc.get_toc()
        except Exception:
            return None
        entries = [
            (level, title.strip(), page - 1)
            for level, title, page in toc
            if 1 <= page <= self.doc.page_count
        ]
        for level in sorted({entry[0] for entry in entries}):
            found = {}
            for entry_level, title, page in entries:
                if entry_level == level and page not in found:
                    found[page] = title or f"Page {page + 1}"
            if len(found) >= 3:
                return [(title, page) for page, title in sorted(found.items())]
        return None

    def heading_starts(self):
        count = self.doc.page_count
        starts = []
        for number in range(count):
            try:
                text = self.doc[number].get_text("text")
            except Exception:
                continue
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            headings = [
                line for line in lines if len(line) <= 60 and HEADING.match(line)
            ]
            if len(headings) >= 3:
                continue
            for line in lines[:4]:
                if len(line) <= 60 and HEADING.match(line):
                    starts.append((line, number))
                    break
        if len(starts) < 2 or len(starts) > count * 0.5:
            return None
        return starts

    def read_image(self, page, block):
        width, height = block.get("width", 0), block.get("height", 0)
        if width * height < MIN_IMAGE_AREA:
            return None
        image = decode_image(block.get("image") or b"")
        if image is not None:
            return image
        try:
            pixmap = page.get_pixmap(
                clip=self.pymupdf.Rect(block["bbox"]),
                dpi=150,
                colorspace=self.pymupdf.csRGB,
                alpha=False,
            )
            image = PILImage.frombytes(
                "RGB", (pixmap.width, pixmap.height), pixmap.samples
            )
            image.thumbnail(MAX_IMAGE_SIZE, PILImage.Resampling.LANCZOS)
            return image
        except Exception:
            return None

    def render_page(self, page):
        try:
            if not page.get_drawings():
                return None
            pixmap = page.get_pixmap(
                dpi=RENDER_DPI, colorspace=self.pymupdf.csRGB, alpha=False
            )
            return PILImage.frombytes(
                "RGB", (pixmap.width, pixmap.height), pixmap.samples
            )
        except Exception:
            return None

    def read_page(self, number):
        page = self.doc[number]
        page_area = max(1.0, page.rect.width * page.rect.height)
        height = page.rect.height
        entries = []
        try:
            blocks = page.get_text("dict", sort=True)["blocks"]
        except Exception:
            blocks = []
        for block in blocks:
            if block["type"] == 0:
                paragraphs = block_paragraphs(block)
                if paragraphs:
                    top, bottom = block["bbox"][1], block["bbox"][3]
                    margin = bottom < height * MARGIN or top > height * (1 - MARGIN)
                    entries.append(
                        {"kind": "text", "paragraphs": paragraphs, "margin": margin}
                    )
            elif block["type"] == 1:
                image = self.read_image(page, block)
                if image is not None:
                    x0, y0, x1, y1 = block["bbox"]
                    cover = (x1 - x0) * (y1 - y0) / page_area
                    entries.append({"kind": "image", "image": image, "cover": cover})

        if any(entry["kind"] == "text" for entry in entries):
            entries = [
                entry
                for entry in entries
                if entry["kind"] == "text" or entry["cover"] < 0.9
            ]
        if not entries:
            image = self.render_page(page)
            if image is not None:
                entries.append({"kind": "image", "image": image, "cover": 1.0})
        return entries

    def blocks(self, index):
        chapter = self.chapters[index]
        pages = []
        with self.lock:
            for number in range(chapter["start"], chapter["end"]):
                try:
                    pages.append(self.read_page(number))
                except Exception:
                    pages.append([])

        repeated = Counter()
        for entries in pages:
            for entry in entries:
                if entry["kind"] == "text" and entry["margin"]:
                    for paragraph in entry["paragraphs"]:
                        repeated[re.sub(r"\d+", "#", paragraph)] += 1

        items = []
        for entries in pages:
            for entry in entries:
                if entry["kind"] == "image":
                    items.append(("image", entry["image"]))
                    continue
                for paragraph in entry["paragraphs"]:
                    if entry["margin"] and (
                        PAGE_NUMBER.match(paragraph)
                        or (
                            len(paragraph) <= 60
                            and repeated[re.sub(r"\d+", "#", paragraph)] >= 2
                        )
                    ):
                        continue
                    previous = items[-1] if items else None
                    if (
                        previous is not None
                        and previous[0] == "text"
                        and not previous[1].endswith(SENTENCE_END)
                        and paragraph[:1].islower()
                    ):
                        items[-1] = ("text", join_paragraphs(previous[1], paragraph))
                    else:
                        items.append(("text", paragraph))

        blocks = []
        texts = []
        for kind, value in items:
            if kind == "text":
                texts.append(value)
                continue
            if texts:
                blocks.append({"type": "text", "content": "\n\n".join(texts)})
                texts = []
            blocks.append({"type": "image", "image": value})
        if texts:
            blocks.append({"type": "text", "content": "\n\n".join(texts)})
        return blocks


def open_book(data):
    if b"%PDF-" in data[:1024]:
        return PdfSource(data)
    if data[:2] == b"PK":
        return EpubSource(data)
    raise BookError("Unsupported file (expected an EPUB or a PDF)")


class LightNovelReaderScreen(Screen):
    BINDINGS = [
        Binding("left", "prev_chapter", "Prev chapter", show=False),
        Binding("right", "next_chapter", "Next chapter", show=False),
        Binding("c", "toggle_counting", "Start/pause count", show=False),
        Binding("r", "reset_counting", "Reset count", show=False),
        Binding("f", "pick_volume", "Pick volume", show=False),
        Binding("l", "chapter_menu", "Chapters", show=False),
        Binding("w", "zoom_in", "Zoom in", show=False),
        Binding("s", "zoom_out", "Zoom out", show=False),
        Binding("escape", "back", "Quit"),
        Binding("q", "back", "Quit"),
    ]

    CSS = """
    LightNovelReaderScreen {
        background: $background;
        layout: vertical;
    }
    #ln-reader {
        height: 1fr;
        padding: 1 4;
        scrollbar-size-vertical: 1;
    }
    .ln-image-row {
        width: 100%;
        height: auto;
        align-horizontal: center;
        margin: 1 0;
    }
    #ln-status {
        height: 1;
        background: $primary;
        color: $background;
        text-align: center;
        text-style: bold;
    }
    """

    def __init__(
        self,
        volumes: list,
        title: str,
        anilist_id: int,
        total_api_chapters: int | None = None,
        token: str | None = None,
        volume_index: int | None = None,
        custom: bool = False,
        start_chapter: int | None = None,
    ):
        super().__init__()
        self.volumes = [str(v) for v in volumes]
        self.volume_index = (
            pick_volume(self.volumes, anilist_id)
            if volume_index is None
            else volume_index
        )
        self.title = title
        self.anilist_id = anilist_id
        self.total_api_chapters = total_api_chapters
        self._start_chapter = start_chapter
        self._forced_index = None

        if custom:
            token = None
        elif not token:
            from anilixy.anilist.login import load_token

            token = load_token()

        self.token = token
        self.source = None
        self.chapters = []
        self.chapter_index = 0
        self.segments = []
        self.auto = False
        self._runs = []
        self.base = 0
        self._entry = None
        self.image_zoom = 0.6
        self._pictures = []
        self._prepared = {}
        self._lock = threading.Lock()
        self._compute_lock = threading.Lock()
        self._anilist_timer = None

    @property
    def book_key(self) -> str:
        return Path(self.volumes[self.volume_index]).name

    @property
    def counting(self) -> bool:
        return bool(self.segments) and self.segments[-1][1] is None

    def anilist_chapter(self) -> int:
        return self.base + counted(
            self.segments, len(self.chapters), upto=self.chapter_index
        )

    def rpc_progress(self):
        if not self.chapters:
            return None
        number = (
            max(1, self.anilist_chapter()) if self.segments else self.chapter_index + 1
        )
        total = self.total_api_chapters
        return f"Chapter {number}" + (f" / {total}" if total else "")

    def persist(self) -> None:
        save_novel_state(
            self.anilist_id,
            self.book_key,
            chapter=self.chapter_index,
            segments=self.segments,
            length=len(self.chapters),
            auto=self.auto,
        )

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="ln-reader"):
            yield Static("Loading book...", id="ln-text")
        yield Static("", id="ln-status")

    def on_mount(self) -> None:
        self.query_one("#ln-reader").focus()
        self.load_book()

    def on_resize(self, event) -> None:
        self.call_after_refresh(self.resize_images)

    def locate_start(self, wanted):
        base = 0
        for v, path in enumerate(self.volumes):
            key = Path(path).name
            state = get_novel_state(self.anilist_id, key)
            segments, length = state["segments"], state.get("length") or 0
            if not segments and not length and str(path).lower().endswith(".epub"):
                try:
                    with open(path, "rb") as f:
                        other = open_book(f.read())
                    segments = detect_chapter_runs(other)
                    length = len(other.chapters)
                    save_novel_state(
                        self.anilist_id,
                        key,
                        touch=False,
                        segments=segments,
                        length=length,
                        auto=bool(segments),
                    )
                except Exception:
                    segments, length = [], 0
            total = counted(segments, length)
            if wanted <= base + total:
                k = wanted - base
                for start, end in segments:
                    stop = length - 1 if end is None else end
                    size = max(0, stop - start + 1)
                    if k <= size:
                        return v, start + k - 1
                    k -= size
            base += total
        return None

    @work(thread=True, group="book")
    def load_book(self) -> None:
        if self._start_chapter:
            target = self.locate_start(self._start_chapter)
            self._start_chapter = None
            if target is not None:
                self.volume_index, self._forced_index = target
            else:
                self.app.call_from_thread(
                    self.notify,
                    "That chapter was not found (EPUB volumes only)",
                    severity="warning",
                )
        try:
            with open(self.volumes[self.volume_index], "rb") as f:
                data = f.read()
            source = open_book(data)
            runs = detect_chapter_runs(source)
            hint = lead_in_index(source, runs)
        except BookError as error:
            self.app.call_from_thread(self.book_failed, str(error))
            return
        except Exception as error:
            self.app.call_from_thread(
                self.book_failed, f"Could not open the book: {error}"
            )
            return
        self.prime_previous()
        self.app.call_from_thread(self.book_loaded, source, runs, hint)

    def prime_previous(self) -> None:
        for path in self.volumes[: self.volume_index]:
            if not str(path).lower().endswith(".epub"):
                continue
            key = Path(path).name
            state = get_novel_state(self.anilist_id, key)
            if state["segments"] or state.get("length"):
                continue
            try:
                with open(path, "rb") as f:
                    other = open_book(f.read())
                runs = detect_chapter_runs(other)
            except Exception:
                continue
            save_novel_state(
                self.anilist_id,
                key,
                touch=False,
                segments=runs,
                length=len(other.chapters),
                auto=bool(runs),
            )

    def book_failed(self, message) -> None:
        self.notify(message, severity="error", timeout=8)
        self.action_back()

    def book_loaded(self, source, runs=None, hint=None) -> None:
        if not self.is_attached:
            return
        if not source.chapters:
            self.notify("No chapters found in the book.", severity="warning")
            self.action_back()
            return
        self.source = source
        self.chapters = source.chapters
        self._runs = runs or []

        state = get_novel_state(self.anilist_id, self.book_key)
        self.segments = state["segments"]
        self.auto = bool(state.get("auto")) and bool(self.segments)
        detected = False
        if not self.segments and self._runs:
            self.segments = [list(run) for run in self._runs]
            self.auto = True
            detected = True
        self.base = base_for(self.anilist_id, self.volumes, self.volume_index)

        last = len(self.chapters) - 1
        if self._forced_index is not None:
            index = self._forced_index
            self._forced_index = None
        elif self._entry == "start":
            if hint is not None:
                index = hint
            else:
                index = self.segments[0][0] if self.segments else 0
        elif self._entry == "end":
            index = last
        else:
            index = state["chapter"]
        self._entry = None
        if not 0 <= index <= last:
            index = 0

        if detected:
            total = counted(self.segments, len(self.chapters))
            self.notify(
                f"Auto-detected {total} chapters (press C to count manually)",
                timeout=5,
            )
        elif not self.segments and len(self.volumes) > 1:
            self.notify(
                "New volume: press C on its first chapter", severity="warning", timeout=6
            )
        self.goto_chapter(index)

    def prepare_chapter(self, index):
        source, volume = self.source, self.volume_index
        key = (volume, index)

        with self._lock:
            cached = self._prepared.get(key)
        if cached is not None:
            return cached

        with self._compute_lock:
            with self._lock:
                cached = self._prepared.get(key)
            if cached is not None:
                return cached
            prepared = source.blocks(index)

        with self._lock:
            self._prepared[key] = prepared
            for k in list(self._prepared):
                if k[0] != volume or abs(k[1] - self.chapter_index) > KEEP_RADIUS:
                    del self._prepared[k]
        return prepared

    def available_width(self) -> int:
        try:
            width = self.query_one("#ln-reader").scrollable_content_region.width
        except Exception:
            width = 0
        if width <= 0:
            width = self.app.size.width - 9
        return max(10, width)

    def image_cells(self, size, available):
        cell_w, cell_h = cell_size()
        width, height = size
        cols = max(4, min(int(available * self.image_zoom), math.ceil(width / cell_w)))
        rows = max(1, math.ceil(cols * cell_w * height / width / cell_h))
        return cols, rows

    def build_widgets(self, blocks):
        available = self.available_width()
        widgets = []
        pictures = []
        for block in blocks:
            if block["type"] == "text":
                widgets.append(Static(Text(block["content"])))
                continue
            image = block["image"]
            cols, rows = self.image_cells(image.size, available)
            picture = TextualImage(image, classes="ln-image")
            picture.styles.width = cols
            picture.styles.height = rows
            widgets.append(Horizontal(picture, classes="ln-image-row"))
            pictures.append((picture, image.size))
        if not widgets:
            widgets.append(Static(Text("(empty page)", style="dim")))
        return widgets, pictures

    def goto_chapter(self, index) -> None:
        self.chapter_index = index
        self.persist()
        self.schedule_anilist()
        self.update_status()
        self.app._update_rpc(self)
        self.render_chapter()

    @work(exclusive=True, group="render")
    async def render_chapter(self) -> None:
        index = self.chapter_index
        try:
            blocks = await asyncio.to_thread(self.prepare_chapter, index)
            if index != self.chapter_index or not self.is_attached:
                return
            reader = self.query_one("#ln-reader", VerticalScroll)
            widgets, pictures = self.build_widgets(blocks)
            self._pictures = pictures
            with self.app.batch_update():
                await reader.remove_children()
                await reader.mount_all(widgets)
                reader.scroll_home(animate=False)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.notify(f"Error showing chapter: {error}", severity="error")
            return
        self.prefetch_neighbors(index)

    @work(thread=True, group="prefetch")
    def prefetch_neighbors(self, index) -> None:
        for target in (index + 1, index - 1):
            if (
                0 <= target < len(self.chapters)
                and abs(target - self.chapter_index) == 1
            ):
                try:
                    self.prepare_chapter(target)
                except Exception:
                    log.debug("ignored error", exc_info=True)

    def schedule_anilist(self) -> None:
        if not self.token or not self.segments:
            return
        progress = self.anilist_chapter()
        if progress <= 0:
            return
        if self.total_api_chapters:
            progress = min(progress, self.total_api_chapters)
        if self._anilist_timer is not None:
            self._anilist_timer.stop()
        self._anilist_timer = self.set_timer(
            1.5, lambda p=progress: self.update_anilist_in_background(p)
        )

    def update_status(self) -> None:
        kind = self.source.kind if self.source else "EPUB"
        chapter_name = (
            self.source.chapter_title(self.chapter_index) if self.source else ""
        )
        label = "AniList" if self.token else "Count"
        if self.auto and self.segments:
            anilist = f"● {label} Ch. {max(1, self.anilist_chapter())} (auto)"
        elif self.counting:
            anilist = f"● {label} Ch. {max(1, self.anilist_chapter())}"
        elif self.segments:
            anilist = f"⏸ {label} Ch. {self.anilist_chapter()}"
        else:
            anilist = f"{label}: press C at Ch.1"

        title = self.title if len(self.title) <= 24 else self.title[:23] + "…"
        volume = (
            f"Vol {self.volume_index + 1}/{len(self.volumes)} "
            if len(self.volumes) > 1
            else ""
        )
        keys = [
            "C Count",
            "R Reset",
            "F Volume",
            "L Chapters",
            "←/→ Chapters",
            "? Help",
            f"W/S Zoom {round(self.image_zoom * 100)}%",
            "Esc Quit",
        ]
        width = max(20, self.size.width or self.app.size.width)

        def build(name, shown_keys):
            chapter = f"{volume}{kind} Ch. {self.chapter_index + 1}/{len(self.chapters)}"
            if name:
                chapter += f" ({name})"
            return " " + " | ".join([title, chapter, anilist] + shown_keys) + " "

        name = chapter_name[:28]
        text = build(name, keys)
        if len(text) > width:
            name = ""
            text = build(name, keys)
        while len(text) > width and len(keys) > 2:
            keys = keys[:-1]
            text = build(name, keys)
        self.query_one("#ln-status", Static).update(Text(text[:width]))

    def set_zoom(self, value) -> None:
        value = round(min(ZOOM_MAX, max(ZOOM_MIN, value)), 1)
        if value == self.image_zoom:
            return
        self.image_zoom = value
        self.resize_images()

    def action_zoom_in(self) -> None:
        self.set_zoom(self.image_zoom + ZOOM_STEP)

    def action_zoom_out(self) -> None:
        self.set_zoom(self.image_zoom - ZOOM_STEP)

    def resize_images(self) -> None:
        if not self.is_attached or not self.chapters:
            return
        available = self.available_width()
        with self.app.batch_update():
            for picture, size in self._pictures:
                if picture.is_attached:
                    cols, rows = self.image_cells(size, available)
                    picture.styles.width = cols
                    picture.styles.height = rows
        self.update_status()

    @work(thread=True, exclusive=True, group="anilist")
    def update_anilist_in_background(self, progress: int) -> None:
        try:
            result = save_manga_progress(self.token, self.anilist_id, chapter=progress)
            if result:
                self.app.call_from_thread(
                    self.notify,
                    f"AniList updated: Chapter {progress}",
                    severity="information",
                    timeout=2,
                )
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

    def action_toggle_counting(self) -> None:
        if not self.chapters:
            return
        index = self.chapter_index

        notice = ""
        if self.auto:
            self.auto = False
            self.segments = []
            notice = "Auto-detect off. "

        if self.counting:
            if index < self.segments[-1][0]:
                self.notify("Go to a chapter after the start", severity="warning")
                return
            self.segments[-1][1] = index
            message = f"Paused. {self.anilist_chapter()} chapters counted"
        else:
            if any(start <= index <= end for start, end in self.segments):
                self.notify("This chapter is already counted", severity="warning")
                return
            self.segments.append([index, None])
            message = f"Counting from chapter {self.anilist_chapter()}"

        self.persist()
        self.notify(notice + message, timeout=3)
        self.update_status()
        self.schedule_anilist()
        self.app._update_rpc(self)

    def action_reset_counting(self) -> None:
        if not self.chapters:
            return
        self.segments = [list(run) for run in self._runs]
        self.auto = bool(self.segments)
        self.persist()
        if self.auto:
            total = counted(self.segments, len(self.chapters))
            self.notify(f"Count reset: auto-detected {total} chapters", timeout=3)
        else:
            self.notify("Count reset for this volume", timeout=3)
        self.update_status()
        self.app._update_rpc(self)

    def open_volume(self, index: int, entry=None) -> None:
        self.volume_index = index
        self._entry = entry
        self.chapters = []
        with self._lock:
            self._prepared.clear()
        self.notify(f"Opening volume {index + 1}/{len(self.volumes)}...")
        self.load_book()

    def change_volume(self, step: int) -> None:
        if step > 0 and self.counting:
            self.notify(
                "Still counting: press C on the last real chapter to stop the extras counting",
                severity="warning",
                timeout=6,
            )
        self.open_volume(self.volume_index + step, "start" if step > 0 else "end")

    def action_pick_volume(self) -> None:
        if not self.chapters:
            return
        if len(self.volumes) < 2:
            self.notify("Only one volume found", severity="warning")
            return
        if not fzf_available():
            self.notify("fzf is not installed", severity="error")
            return
        picked = pick_path(self.app, self.volumes)
        if picked is None:
            return
        index = self.volumes.index(picked)
        if index != self.volume_index:
            self.open_volume(index)

    def action_chapter_menu(self) -> None:
        if not self.chapters:
            return
        labels = []
        for i in range(len(self.chapters)):
            try:
                name = self.source.chapter_title(i)
            except Exception:
                name = ""
            labels.append(f"{i + 1}. {name}" if name else str(i + 1))

        def closed(index) -> None:
            if index is not None and index != self.chapter_index:
                self.goto_chapter(index)

        self.app.push_screen(ChapterPickerScreen(labels, self.chapter_index), closed)

    def action_prev_chapter(self) -> None:
        if not self.chapters:
            return
        if self.chapter_index > 0:
            self.goto_chapter(self.chapter_index - 1)
        elif self.volume_index > 0:
            self.change_volume(-1)
        else:
            self.notify("First chapter", severity="warning")

    def action_next_chapter(self) -> None:
        if not self.chapters:
            return
        if self.chapter_index < len(self.chapters) - 1:
            self.goto_chapter(self.chapter_index + 1)
        elif self.volume_index < len(self.volumes) - 1:
            self.change_volume(1)
        else:
            self.notify("Last chapter", severity="warning")

    def action_back(self) -> None:
        self.app.pop_screen()
