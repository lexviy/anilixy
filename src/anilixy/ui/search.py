from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import (
    Input,
    OptionList,
    Static,
)
from textual.widgets.option_list import Option

from anilixy.anilist.api import (
    search_anime,
    search_character,
    search_manga,
    search_staff,
    search_studio,
)
from anilixy.anime.screen import AnimeScreen
from anilixy.manga.screen import MangaScreen
from anilixy.ui.animations import Backdrop
from anilixy.ui.people import CharacterScreen, StaffScreen
from anilixy.ui.studio import StudioScreen


class BaseSearchScreen(Screen):
    BINDINGS = [("escape", "app.pop_screen")]
    TITLE_TEXT = ""
    PLACEHOLDER = ""
    FOOTER = "Esc to go back"
    NO_RESULTS = "No results found"

    def __init__(self):
        super().__init__()
        self.results = {}
        self.search_id = 0

    def compose(self) -> ComposeResult:
        yield Backdrop()
        with Vertical(id="search-box"):
            yield Static(self.TITLE_TEXT, classes="box-title")
            yield Input(placeholder=self.PLACEHOLDER, id="query")
            yield Static("", id="count")
            yield OptionList(id="results")
            yield Static(self.FOOTER)

    def search(self, name):
        raise NotImplementedError

    def option_for(self, item):
        raise NotImplementedError

    def open_result(self, value) -> None:
        raise NotImplementedError

    def on_input_submitted(self, event: Input.Submitted) -> None:
        name = event.value.strip()
        if not name:
            return
        self.search_id += 1
        self.query_one("#count", Static).update("Searching...")
        self.run_search(name, self.search_id)

    @work(thread=True)
    def run_search(self, name, search_id) -> None:
        try:
            items = self.search(name)
        except Exception:
            self.app.call_from_thread(self.search_failed, search_id)
            return
        self.app.call_from_thread(self.show_results, items, search_id)

    def search_failed(self, search_id) -> None:
        if search_id != self.search_id or not self.is_attached:
            return
        self.query_one("#count", Static).update("")
        self.notify("Search failed", severity="error")

    def show_results(self, items, search_id) -> None:
        if search_id != self.search_id or not self.is_attached:
            return
        count = self.query_one("#count", Static)
        if not items:
            count.update("")
            self.notify(self.NO_RESULTS, severity="warning")
            return
        results_list = self.query_one("#results", OptionList)
        results_list.clear_options()
        self.results = {}
        options = []
        for item in items:
            key, label, value = self.option_for(item)
            self.results[str(key)] = value
            options.append(Option(Text(label), id=str(key)))
        results_list.add_options(options)
        results_list.display = True
        results_list.highlighted = 0
        results_list.focus()
        count.update(f"{len(items)} results")

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.open_result(self.results[event.option.id])


class SearchScreen(BaseSearchScreen):
    TITLE_TEXT = "Search anime: "
    PLACEHOLDER = "Anime name (Enter to search)"
    FOOTER = "Esc to go back  |  PageUp/PageDown to jump between pages"
    NO_RESULTS = "No results found, please try again"

    def search(self, name):
        return search_anime(name)

    def option_for(self, a):
        title = a["title"]["english"] or a["title"]["romaji"]
        details = ", ".join(str(x) for x in (a["format"], a["seasonYear"]) if x)
        label = f"{title} ({details})" if details else title
        return a["id"], label, a

    def open_result(self, anime) -> None:
        self.app.push_screen(AnimeScreen(anime))


class MangaSearchScreen(BaseSearchScreen):
    TITLE_TEXT = "Search manga/light novel: "
    PLACEHOLDER = "Title (Enter to search)"
    FOOTER = "Esc to go back  |  PageUp/PageDown to jump between pages"

    def search(self, name):
        return search_manga(name)

    def option_for(self, a):
        title = a["title"]["english"] or a["title"]["romaji"]
        details = ", ".join(
            str(x) for x in (a.get("format"), a.get("seasonYear")) if x
        )
        label = f"{title} ({details})" if details else title
        return a["id"], label, a

    def open_result(self, manga) -> None:
        self.app.push_screen(MangaScreen(manga))


class CharacterSearchScreen(BaseSearchScreen):
    TITLE_TEXT = "Search character: "
    PLACEHOLDER = "Character name (Enter to search)"
    NO_RESULTS = "No results found, please try again"

    def search(self, name):
        return search_character(name)

    def option_for(self, c):
        label = c["name"]["full"] or c["name"].get("native") or "?"
        return c["id"], label, c["id"]

    def open_result(self, char_id) -> None:
        self.app.push_screen(CharacterScreen(char_id))


class StaffSearchScreen(BaseSearchScreen):
    TITLE_TEXT = "Search staff: "
    PLACEHOLDER = "Staff name (Enter to search)"

    def search(self, name):
        return search_staff(name)

    def option_for(self, s):
        label = s["name"]["full"] or s["name"].get("native") or "?"
        return s["id"], label, s["id"]

    def open_result(self, staff_id) -> None:
        self.app.push_screen(StaffScreen(staff_id))


class StudioSearchScreen(BaseSearchScreen):
    TITLE_TEXT = "Search studio: "
    PLACEHOLDER = "Studio name (Enter to search)"

    def search(self, name):
        return search_studio(name)

    def option_for(self, st):
        return st["id"], st.get("name") or "?", st

    def open_result(self, st) -> None:
        self.app.push_screen(StudioScreen(st["id"], st["name"]))
