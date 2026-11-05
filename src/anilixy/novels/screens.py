import logging
from pathlib import Path

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import (
    Button,
    Input,
    OptionList,
    Static,
)
from textual.widgets.option_list import Option

from anilixy.anilist.api import fetch_reading
from anilixy.anilist.profile import fetch_profile
from anilixy.core.browser import open_url
from anilixy.core.settings import load_ln_folder
from anilixy.manga import new_chapters
from anilixy.manga.history import get_mapping
from anilixy.manga.reader import MangaReaderScreen
from anilixy.manga.sources import source_for
from anilixy.novels import custom as custom_novels
from anilixy.novels import jnovels
from anilixy.novels.reader import LightNovelReaderScreen
from anilixy.novels.reading import last_read
from anilixy.ui.animations import Backdrop
from anilixy.ui.dialogs import ConfirmScreen
from anilixy.ui.picker import fzf_available, pick_path, pick_paths

log = logging.getLogger(__name__)


def open_light_novel(
    app, volumes, title, anilist_id, chapters, custom=False, resume=False,
    start_chapter=None,
) -> None:
    volumes = [str(v) for v in volumes]
    index = None
    last = last_read(anilist_id)
    has_history = last is not None and any(Path(v).name == last[0] for v in volumes)
    if (
        len(volumes) > 1
        and fzf_available()
        and not (resume and has_history)
        and not start_chapter
    ):
        picked = pick_path(app, volumes)
        if picked is None:
            app.notify("Cancelled", severity="warning")
            return
        index = volumes.index(picked)
    app.push_screen(
        LightNovelReaderScreen(
            volumes,
            title,
            anilist_id,
            chapters,
            app.token,
            volume_index=index,
            custom=custom,
            start_chapter=start_chapter,
        )
    )


def open_custom_novel(app, entry) -> None:
    entry = custom_novels.get(entry["id"]) or entry
    volumes = custom_novels.volumes(entry)
    if not volumes:
        if entry.get("files"):
            message = "None of the selected files exist anymore (press E to choose again)"
        else:
            message = f"No files matching '{entry['title']}' in {load_ln_folder()}"
        app.notify(message, severity="warning", timeout=6)
        return
    open_light_novel(app, volumes, entry["title"], entry["id"], None, custom=True, resume=True)


def novel_titles(media) -> list[str]:
    titles = media.get("title") or {}
    found = []
    for key in ("english", "romaji"):
        value = titles.get(key)
        if value and value not in found:
            found.append(value)
    return found


def read_light_novel(app, media, start_chapter=None, resume=False) -> None:
    titles = novel_titles(media)
    if not titles:
        app.call_from_thread(app.notify, "No title to search.", severity="warning")
        return
    for title in titles:
        volumes = jnovels.get_local_volumes(title)
        if volumes:
            app.call_from_thread(
                open_light_novel,
                app, volumes, title, media["id"], media.get("chapters"),
                resume=resume, start_chapter=start_chapter,
            )
            return
    app.call_from_thread(
        app.notify, "Book not found locally. Searching JNovels...", timeout=3
    )
    for title in titles:
        try:
            page, volumes = jnovels.find_work(title)
        except Exception:
            log.warning("JNovels search failed for %r", title, exc_info=True)
            continue
        if page:
            app.call_from_thread(
                app.push_screen, JNovelsVolumesScreen(title, page, volumes)
            )
            return
    app.call_from_thread(app.notify, "Not found on JNovels.", severity="warning")


class JNovelsVolumesScreen(ModalScreen):
    BINDINGS = [("escape", "app.pop_screen", "Close")]

    def __init__(self, title, page, volumes) -> None:
        super().__init__()
        self.title_text = title
        self.page = page
        self.volumes = volumes

    def compose(self) -> ComposeResult:
        with Vertical(id="jnovels-box"):
            yield Static(f"{self.title_text} on JNovels", classes="box-title")
            yield Static(
                f"Not in {load_ln_folder()}. Pick a volume to open its download "
                "link in the browser, then save the EPUB or PDF to that folder.",
                id="jnovels-hint",
            )
            options = [Option("Open the JNovels page", id="page")]
            options += [
                Option(volume["title"], id=str(index))
                for index, volume in enumerate(self.volumes)
            ]
            yield OptionList(*options, id="jnovels-list")
            with Horizontal(id="jnovels-buttons"):
                yield Button("Close", id="jnovels-close")

    def on_mount(self) -> None:
        self.query_one("#jnovels-list", OptionList).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option.id == "page":
            open_url(self.page)
        else:
            volume = self.volumes[int(event.option.id)]
            open_url(volume["url"])
            self.notify(f"Opened {volume['title']}", timeout=3)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "jnovels-close":
            self.app.pop_screen()

class CustomNovelModal(ModalScreen):
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, title="", files=None, editing=False) -> None:
        super().__init__()
        self.initial_title = title
        self.files = list(files) if files else None
        self.editing = editing

    def compose(self) -> ComposeResult:
        with Vertical(id="add-custom-box"):
            yield Static("Edit light novel" if self.editing else "Add light novel", classes="box-title")
            yield Input(value=self.initial_title, placeholder="Title", id="custom-title")
            yield Static("", id="add-custom-hint")
            with Horizontal(id="add-custom-buttons"):
                yield Button("Save" if self.editing else "Add", id="add-custom-ok", variant="success")
                yield Button("Pick files (fzf)", id="add-custom-files")
                yield Button("Match by title", id="add-custom-bytitle")
                yield Button("Cancel", id="add-custom-cancel")

    def on_mount(self) -> None:
        self.query_one("#custom-title", Input).focus()
        self.update_hint()

    def update_hint(self) -> None:
        if self.files:
            text = (
                f"{len(self.files)} file(s) chosen by hand. The title can be anything, "
                "it does not have to match the file names."
            )
        else:
            text = (
                f"Files are found by title: the names in {load_ln_folder()} must contain it. "
                "Use Pick files to choose them by hand (Tab selects several)."
            )
        self.query_one("#add-custom-hint", Static).update(Text(text))

    def pick_files(self) -> None:
        if not fzf_available():
            self.notify("fzf is not installed", severity="error")
            return
        books = sorted(jnovels.list_books(), key=jnovels.natural_key)
        if not books:
            self.notify(f"No EPUB/PDF files in {load_ln_folder()}", severity="warning", timeout=6)
            return
        picked = pick_paths(self.app, [str(b) for b in books])
        if not picked:
            return
        self.files = picked
        field = self.query_one("#custom-title", Input)
        if not field.value.strip():
            field.value = custom_novels.guess_title(picked[0])
        self.update_hint()

    def choose(self) -> None:
        title = self.query_one("#custom-title", Input).value.strip()
        if not title and self.files:
            title = custom_novels.guess_title(self.files[0])
        if not title:
            self.notify("Type a title", severity="warning")
            return
        if not self.files and not jnovels.get_local_volumes(title):
            self.notify(
                f"No EPUB/PDF in {load_ln_folder()} matches this title (try Pick files)",
                severity="warning",
                timeout=6,
            )
            return
        self.dismiss({"title": title, "files": self.files})

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button = event.button.id
        if button == "add-custom-ok":
            self.choose()
        elif button == "add-custom-files":
            self.pick_files()
        elif button == "add-custom-bytitle":
            self.files = None
            self.update_hint()
        else:
            self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.choose()

    def action_cancel(self) -> None:
        self.dismiss(None)


class KeepReadingScreen(Screen):
    BINDINGS = [("escape", "app.pop_screen", "Back")]

    def __init__(self):
        super().__init__()
        self.items = {}

    def compose(self) -> ComposeResult:
        yield Backdrop()
        with Vertical(id="keep-box"):
            yield Static("Keep reading", classes="box-title")
            yield Static("Loading...", id="keep-count")
            yield OptionList(id="keep-list")
            yield Static("Enter / click: read manga/novel  |  Esc: back")

    def on_mount(self) -> None:
        self.load_list()

    @work(thread=True)
    def load_list(self) -> None:
        if self.app.guest:
            self.app.call_from_thread(self.fill_list, [])
            return
        try:
            profile = self.app.profile or fetch_profile(self.app.token)
            if profile is None:
                self.app.call_from_thread(
                    self.notify, "Session expired", severity="error"
                )
                self.app.call_from_thread(self.fill_list, [])
                return
            entries = fetch_reading(self.app.token, profile["id"])
            self.app.call_from_thread(self.fill_list, entries, new_chapters.cached_unread(entries))
            unread = new_chapters.check(entries)["unread"]
            self.app.call_from_thread(self.fill_list, entries, unread)
        except Exception as e:
            self.app.call_from_thread(
                self.notify, f"Failed to load reading list: {e}", severity="error"
            )
            self.app.call_from_thread(self.fill_list, [])

    def fill_list(self, entries, unread=None) -> None:
        if not self.is_attached:
            return
        unread = unread or {}
        accent = self.app.get_css_variables().get("accent", "yellow")
        option_list = self.query_one("#keep-list", OptionList)
        highlighted = option_list.highlighted
        option_list.clear_options()
        self.items = {}
        options = []
        for entry in entries:
            media = entry["media"]
            progress = entry.get("progress") or 0
            total = media.get("chapters")
            title = media["title"]["english"] or media["title"]["romaji"] or "?"

            text = Text(title)
            latest = unread.get(str(media["id"]))
            if latest is not None:
                new = latest - progress
                label = f"{new:g} new" if new >= 1 else "new"
                text.append(f" ({label}!)", style=f"bold {accent}")
            tag = " · rereading" if entry.get("status") == "REPEATING" else ""
            text.append(f"  Ch {progress}/{total or '?'}{tag}", style="dim")

            self.items[str(media["id"])] = media
            options.append(Option(text, id=str(media["id"])))

        for entry in custom_novels.list_entries():
            self.items[entry["id"]] = {
                "custom": True,
                "id": entry["id"],
                "title": entry["title"],
            }
            text = Text(entry["title"])
            text.append(
                "  " + custom_novels.progress_label(entry["id"]), style="dim"
            )
            options.append(Option(text, id=entry["id"]))

        count = self.query_one("#keep-count", Static)
        if not options:
            count.update("Nothing in your Reading list")
            return
        option_list.add_options(options)
        option_list.focus()
        if highlighted is not None and highlighted < len(options):
            option_list.highlighted = highlighted
        count.update(f"{len(options)} titles")

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        media = self.items[event.option.id]
        if media.get("custom"):
            open_custom_novel(self.app, media)
            return
        manga_id = media["id"]

        if media.get("format") == "NOVEL":
            self.open_novel(media)
            return

        mapping = get_mapping(manga_id)
        if source_for(mapping):
            title = media["title"]["english"] or media["title"]["romaji"] or ""
            self.app.push_screen(MangaReaderScreen(manga_id, mapping, title))
        else:
            self.app.open_anime(manga_id)

    @work(thread=True)
    def open_novel(self, media) -> None:
        read_light_novel(self.app, media, resume=True)


class CustomNovelsScreen(Screen):
    BINDINGS = [
        ("escape", "app.pop_screen", "Back"),
        ("a", "add_novel", "Add"),
        ("e", "edit_novel", "Edit"),
        ("r", "remove_novel", "Remove"),
    ]

    def compose(self) -> ComposeResult:
        yield Backdrop()
        with Vertical(id="custom-box"):
            yield Static("Custom light novels", classes="box-title")
            yield Static("", id="custom-count")
            yield OptionList(id="custom-list")
            with Horizontal(id="custom-buttons"):
                yield Button("Add (A)", id="custom-add", variant="success")
                yield Button("Edit (E)", id="custom-edit", variant="primary")
                yield Button("Remove (R)", id="custom-remove", variant="error")
                yield Button("Back", id="custom-back")
            yield Static("Enter: read  |  A: add  |  E: edit  |  R: remove  |  Esc: back")

    def on_mount(self) -> None:
        self.refresh_list()

    def refresh_list(self, select=None) -> None:
        entries = custom_novels.list_entries()
        option_list = self.query_one("#custom-list", OptionList)
        option_list.clear_options()
        options = []
        for entry in entries:
            found = len(custom_novels.volumes(entry))
            text = Text(entry["title"])
            if found:
                source = "chosen" if entry["files"] else "by title"
                text.append(
                    f"  {found} file{'s' if found != 1 else ''} ({source})", style="dim"
                )
            else:
                text.append("  no files found", style="bold red")
            options.append(Option(text, id=entry["id"]))
        option_list.add_options(options)
        count = self.query_one("#custom-count", Static)
        if not entries:
            count.update("No custom light novels yet (press A to add one)")
            return
        count.update(f"{len(entries)} light novel{'s' if len(entries) != 1 else ''}")
        ids = [entry["id"] for entry in entries]
        option_list.highlighted = ids.index(select) if select in ids else 0
        option_list.focus()

    def selected_entry(self):
        option_list = self.query_one("#custom-list", OptionList)
        index = option_list.highlighted
        if index is None or option_list.option_count == 0:
            return None
        return custom_novels.get(option_list.get_option_at_index(index).id)

    def action_add_novel(self) -> None:
        self.app.push_screen(CustomNovelModal(), self.novel_added)

    def novel_added(self, result) -> None:
        if not result or not self.is_attached:
            return
        key, created = custom_novels.add(result["title"], result["files"])
        self.refresh_list(select=key)
        if created:
            self.notify(f"Added: {result['title']}")
        else:
            self.notify("That light novel is already in the list", severity="warning")

    def action_edit_novel(self) -> None:
        entry = self.selected_entry()
        if entry is None:
            self.notify("Nothing selected", severity="warning")
            return
        self.app.push_screen(
            CustomNovelModal(entry["title"], entry["files"], editing=True),
            lambda result, key=entry["id"]: self.novel_edited(result, key),
        )

    def novel_edited(self, result, key) -> None:
        if not result or not self.is_attached:
            return
        custom_novels.update(key, result["title"], result["files"])
        self.refresh_list(select=key)
        self.notify("Saved (your reading progress is kept)")

    def action_remove_novel(self) -> None:
        entry = self.selected_entry()
        if entry is None:
            self.notify("Nothing selected", severity="warning")
            return
        self.app.push_screen(
            ConfirmScreen(
                f"Remove '{entry['title']}'?",
                "It disappears from Keep reading and its reading progress is deleted. "
                "The files stay in your folder.",
            ),
            lambda yes, key=entry["id"]: self.removal_answered(yes, key),
        )

    def removal_answered(self, yes, key) -> None:
        if not yes or not self.is_attached:
            return
        custom_novels.remove(key)
        self.refresh_list()
        self.notify("Removed")

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        entry = custom_novels.get(event.option.id)
        if entry is not None:
            open_custom_novel(self.app, entry)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "custom-add":
            self.action_add_novel()
        elif event.button.id == "custom-edit":
            self.action_edit_novel()
        elif event.button.id == "custom-remove":
            self.action_remove_novel()
        elif event.button.id == "custom-back":
            self.app.pop_screen()
