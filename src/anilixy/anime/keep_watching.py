import requests
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import (
    OptionList,
    Static,
)
from textual.widgets.option_list import Option, OptionDoesNotExist

from anilixy.anilist.api import fetch_watching
from anilixy.anilist.profile import fetch_profile
from anilixy.anime.new_episodes import check_new, mark_seen
from anilixy.anime.progress import local_entries
from anilixy.anime.resume import clear_resume, format_time, load_resumes
from anilixy.anime.watching import watch
from anilixy.ui.animations import Backdrop


class KeepWatchingScreen(Screen):
    BINDINGS = [("escape", "app.pop_screen", "Back")]

    def __init__(self):
        super().__init__()
        self.items = {}
        self.new_eps = {}
        self.entries = []
        self.offline = False
        self.keep_key = None

    def compose(self) -> ComposeResult:
        yield Backdrop()
        with Vertical(id="keep-box"):
            yield Static("Keep watching", classes="box-title")
            yield Static("Loading...", id="keep-count")
            yield OptionList(id="keep-list")
            yield Static("Enter / click: continue where you left  |  Esc: back")

    def on_mount(self) -> None:
        self.load_list()

    @work(thread=True)
    def load_list(self) -> None:
        entries = []
        offline = False
        if self.app.guest:
            entries = local_entries()
        else:
            try:
                profile = self.app.profile or fetch_profile(self.app.token)
                if profile is None:
                    self.app.call_from_thread(
                        self.notify, "Session expired", severity="error"
                    )
                else:
                    entries = fetch_watching(self.app.token, profile["id"])
            except requests.RequestException:
                offline = True
        self.app.call_from_thread(self.fill_list, entries, offline)

    def fill_list(self, entries, offline) -> None:
        if not self.is_attached:
            return
        self.entries = entries
        self.offline = offline
        self.new_eps = check_new(entries)
        new_eps = self.new_eps
        accent = self.app.get_css_variables().get("accent", "yellow")
        option_list = self.query_one("#keep-list", OptionList)
        option_list.clear_options()
        self.items = {}
        anilist = {str(e["media"]["id"]): e for e in entries}
        options = []

        resumes = load_resumes()
        for key, saved in sorted(
            resumes.items(), key=lambda kv: kv[1].get("updated", 0), reverse=True
        ):
            entry = anilist.get(key)
            if entry is None and not self.app.guest and not offline:
                continue
            if entry is not None and saved["episode"] <= (entry["progress"] or 0):
                clear_resume(key)
                continue
            rewatching = entry is not None and entry.get("status") == "REPEATING"
            names = saved["title"]
            title = names.get("english") or names.get("romaji") or "?"
            text = Text(title)
            if key in new_eps:
                text.append(" (new ep!)", style=f"bold {accent}")
            text.append(
                f"  ep {saved['episode']} · resume at {format_time(saved['position'])}"
                + (" · rewatching" if rewatching else ""),
                style="dim",
            )
            self.items[key] = {
                "anime": {
                    "id": int(key),
                    "title": names,
                    "episodes": saved.get("episodes"),
                },
                "episode": saved["episode"],
            }
            options.append(Option(text, id=key))

        for key, entry in anilist.items():
            if key in self.items:
                continue
            media = entry["media"]
            progress = entry["progress"] or 0
            total = media["episodes"]
            airing = media["nextAiringEpisode"]
            released = airing["episode"] - 1 if airing else total
            up_to_date = released is not None and progress >= released
            title = media["title"]["english"] or media["title"]["romaji"] or "?"
            tag = " · rewatching" if entry.get("status") == "REPEATING" else ""
            text = Text(title)
            if key in new_eps:
                text.append(" (new ep!)", style=f"bold {accent}")
            if up_to_date:
                text.append(
                    f"  {progress}/{total or '?'} · up to date{tag}", style="dim"
                )
            else:
                text.append(
                    f"  {progress}/{total or '?'} · next: ep {progress + 1}{tag}",
                    style="dim",
                )
            self.items[key] = {
                "anime": {
                    "id": media["id"],
                    "title": media["title"],
                    "episodes": media["episodes"],
                },
                "episode": progress + 1,
            }
            options.append(Option(text, id=key, disabled=up_to_date))

        count = self.query_one("#keep-count", Static)
        if not options:
            count.update("Offline" if offline else "Nothing in your Watching list")
            return
        option_list.add_options(options)
        option_list.focus()
        count.update(f"{len(options)} anime" + (" (offline)" if offline else ""))
        if self.keep_key is not None:
            try:
                option_list.highlighted = option_list.get_option_index(self.keep_key)
            except OptionDoesNotExist:
                pass

    def refresh_list(self) -> None:
        self.fill_list(self.entries, self.offline)
        self.load_list()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        item = self.items[event.option.id]
        self.keep_key = event.option.id
        released = self.new_eps.get(event.option.id)
        if released:
            mark_seen(event.option.id, released)
        watch(self.app, item["anime"], item["episode"])
        self.refresh_list()
