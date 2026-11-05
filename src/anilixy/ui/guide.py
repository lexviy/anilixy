from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static, TabbedContent, TabPane

GUIDE = [
    (
        "guide-general",
        "General",
        [
            (
                "Getting started",
                [
                    "Log in with your AniList account (you need a client ID from "
                    "anilist.co/settings/developer) or continue as a guest.",
                    "Guests can watch and read too, but progress stays on this computer "
                    "and lists, favourites and notifications need an account.",
                    "Press ? on any screen to see its keys. Ctrl+Q quits from anywhere.",
                ],
            ),
            (
                "Main menu",
                [
                    "Keep watching / Keep reading: everything you are watching or reading, "
                    "ready to continue.",
                    "Search anime, manga/light novel, character, staff or studio and open "
                    "any result to see its page.",
                    "My AniList: your profile, lists, favourites and stats.",
                    "Change theme / animation: the colours and the animated background.",
                ],
            ),
            (
                "Title pages",
                [
                    "Every anime, manga and light novel page has tabs (1-4): Information, "
                    "Staff & Characters, Related and Recommendations.",
                    "Click the ☆ to add or remove a favourite. Add to list edits your "
                    "AniList entry (status, progress, score).",
                    "The box at the bottom holds the main buttons: Watch / Read, Add to list "
                    "and Back.",
                ],
            ),
            (
                "Requirements",
                [
                    "mpv and ani-cli to watch anime, fzf to pick between results "
                    "(without fzf the first result is used).",
                ],
            ),
        ],
    ),
    (
        "guide-anime",
        "Anime",
        [
            (
                "Watching",
                [
                    "Open an anime and press Watch. The episode box shows auto (N): with it "
                    "empty, Watch plays the next episode after your AniList progress.",
                    "Type a number in the box to play a different episode.",
                    "If you stopped in the middle of an episode, Watch resumes it at the "
                    "minute where you left.",
                    "Episodes are played by ani-cli in mpv. In mpv, N / P jump to the "
                    "next / previous episode.",
                ],
            ),
            (
                "Progress",
                [
                    "When you watch most of an episode, AniList progress goes up by one; "
                    "at the last episode the anime is marked Completed.",
                    "Planning, Paused or Dropped anime with progress continue where you "
                    "were and become Watching. Completed anime start again as Rewatching.",
                    "The next episode starts by itself after the autoplay delay "
                    "(Settings).",
                ],
            ),
            (
                "Source",
                [
                    "The first time, pick the right series in ani-cli; it is remembered. "
                    "Reset source makes it ask again.",
                    "Video quality and dubbed version are set in Settings.",
                ],
            ),
            (
                "Keep watching",
                [
                    "Lists your Watching anime and the ones you paused mid-episode. "
                    "(new ep!) marks an episode that came out after your progress.",
                ],
            ),
        ],
    ),
    (
        "guide-manga",
        "Manga",
        [
            (
                "Reading",
                [
                    "Open a manga and press Read. Leave the chapter box empty to continue "
                    "where you stopped, or type a chapter number.",
                    "Chapters come from WeebCentral; if it doesn't have the manga, "
                    "MangaTown is tried. Pick the right series in fzf; it is remembered.",
                    "The Source button shows where the manga comes from and lets you "
                    "search another source or forget the saved series.",
                ],
            ),
            (
                "Reader keys",
                [
                    "← / → change page (at the ends, the chapter). P / N previous / next "
                    "chapter. L opens the chapter menu.",
                    "C switches between page and webtoon (long strip) mode. D shows two "
                    "pages side by side, F shifts the pairing.",
                    "W / S zoom, 0 resets. Esc closes the reader; your page is saved.",
                ],
            ),
            (
                "Offline",
                [
                    "O saves the current chapter to read without internet; Shift+O opens the "
                    "chapter list to pick which ones to save (Space marks, A marks all, "
                    "Enter downloads). Saved chapters show [offline] in the status bar.",
                    "Without internet the reader lists only the chapters you saved. "
                    "Clear downloads in Settings deletes them.",
                ],
            ),
            (
                "Progress and new chapters",
                [
                    "Finishing a chapter updates your AniList progress.",
                    "Keep reading shows (N new!) when the source has chapters after your "
                    "progress, and you get a notification when a new one comes out.",
                ],
            ),
        ],
    ),
    (
        "guide-novels",
        "Light novels",
        [
            (
                "Where the books come from",
                [
                    "Light novels are read from EPUB or PDF files in your light novels "
                    "folder (Settings → Light novels folder).",
                    "Files are matched by title, so keep the series name in the file "
                    "name, e.g. 'Classroom of the Elite Vol. 1.epub'.",
                    "If the book is not in the folder, Read shows its volumes on JNovels: "
                    "pick one to open the download in the browser, then save it to the folder.",
                ],
            ),
            (
                "Reading",
                [
                    "Read opens the volume you were reading at the same place. With several "
                    "volumes, fzf asks which one (F changes volume inside the reader).",
                    "← / → previous / next chapter (at the ends, the volume). L chapter "
                    "menu. W / S zoom images.",
                ],
            ),
            (
                "AniList progress",
                [
                    "The reader counts chapters for AniList by itself. C starts / pauses "
                    "the count manually, R resets it for this volume.",
                    "Type an AniList chapter in the box on the page to start from it; the "
                    "reader finds the right volume.",
                ],
            ),
            (
                "Custom light novels",
                [
                    "Main menu → Custom light novels: add books that aren't on AniList. "
                    "A adds, E renames or changes files, R removes.",
                ],
            ),
        ],
    ),
    (
        "guide-data",
        "Alerts & data",
        [
            (
                "Notifications",
                [
                    "While Anilixy is open it checks for new episodes and chapters a few "
                    "seconds after starting and then every 30 minutes.",
                    "You get a message in the app and a desktop notification (notify-send). "
                    "Turn desktop notifications off in Settings.",
                    "Manga chapters are only checked for manga that already have a "
                    "saved source.",
                ],
            ),
            (
                "Where things are saved",
                [
                    "~/.config/anilixy: login, settings, progress and saved sources.",
                    "~/.cache/anilixy: covers, AniList pages and the log "
                    "(anilixy.log). Clean cache in Settings empties it.",
                    "~/.local/share/anilixy/manga: chapters saved offline.",
                    "Discord Rich Presence shows what you are watching or reading; "
                    "turn it off in Settings.",
                ],
            ),
        ],
    ),
]


def render_tab(sections) -> Text:
    text = Text()
    for index, (heading, lines) in enumerate(sections):
        if index:
            text.append("\n")
        text.append(heading + "\n", style="bold underline")
        for line in lines:
            text.append("  • ", style="bold")
            text.append(line + "\n")
    return text


class GuideScreen(ModalScreen):
    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("q", "close", "Close", show=False),
    ] + [
        Binding(str(number), f"show_tab('{tab_id}')", show=False)
        for number, (tab_id, _, _) in enumerate(GUIDE, start=1)
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="guide-box"):
            yield Static("How Anilixy works", classes="box-title")
            with TabbedContent(id="guide-tabs"):
                for tab_id, title, sections in GUIDE:
                    with TabPane(title, id=tab_id):
                        with VerticalScroll(classes="guide-scroll"):
                            yield Static(render_tab(sections), classes="guide-text")
            with Horizontal(id="guide-buttons"):
                yield Static(
                    f"1-{len(GUIDE)}: switch tab  ·  ↑ / ↓: scroll  ·  Esc: close",
                    id="guide-hint",
                )
                yield Button("Close", id="guide-close")

    def action_show_tab(self, tab_id: str) -> None:
        self.query_one("#guide-tabs", TabbedContent).active = tab_id

    def action_close(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "guide-close":
            self.dismiss(None)
