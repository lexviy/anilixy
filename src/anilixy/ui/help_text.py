HELP = {
    "MenuScreen": (
        "Main menu",
        [
            ("↑ / ↓", "Move between options"),
            ("Enter", "Open the option"),
            ("Ctrl+Q", "Quit Anilixy"),
        ],
    ),
    "BaseSearchScreen": (
        "Search",
        [
            ("Enter", "Search (while typing in the box)"),
            ("↓ / Tab", "Move to the results"),
            ("Enter", "Open the highlighted result"),
            ("PageUp / PageDown", "Jump between result pages"),
            ("Esc", "Back"),
        ],
    ),
    "KeepWatchingScreen": (
        "Keep watching",
        [
            ("Enter / click", "Continue where you left off"),
            ("Esc", "Back"),
            ("", ""),
            ("In mpv", ""),
            ("N", "Next episode"),
            ("P", "Previous episode"),
        ],
    ),
    "KeepReadingScreen": (
        "Keep reading",
        [
            ("Enter / click", "Open the manga or light novel (resumes where you stopped)"),
            ("(N new!)", "Chapters released after your AniList progress"),
            ("Esc", "Back"),
        ],
    ),
    "CustomNovelsScreen": (
        "Custom light novels",
        [
            ("Enter", "Read (resumes the last volume)"),
            ("A", "Add a light novel"),
            ("E", "Edit: rename it or change its files"),
            ("R", "Remove it (asks for confirmation)"),
            ("Esc", "Back"),
        ],
    ),
    "MyAniListScreen": (
        "My AniList",
        [
            ("1 – 5", "Overview, Anime list, Manga/Light Novel, Favorites, Stats"),
            ("Tab", "Move between buttons and titles"),
            ("Enter / click", "Open a title"),
            ("Esc", "Back"),
        ],
    ),
    "AnimeScreen": (
        "Anime",
        [
            ("1 – 4", "Information, Staff & Characters, Related, Recommendations"),
            ("← / →", "Move between buttons"),
            ("☆ (click)", "Add or remove from favourites"),
            ("Watch", "Play the episode in the box"),
            ("Reset source", "Choose the ani-cli source again next time"),
            ("Esc", "Back"),
        ],
    ),
    "MangaScreen": (
        "Manga / light novel",
        [
            ("1 – 4", "Information, Staff & Characters, Related, Recommendations"),
            ("← / →", "Move between buttons"),
            ("☆ (click)", "Add or remove from favourites"),
            ("Chapter box", "Chapter to start at (manga: prefilled; light novels: AniList chapter)"),
            ("Read", "Open the reader (light novels: pick a volume with fzf)"),
            ("Source", "Pick WeebCentral / MangaTown, or forget the saved series"),
            ("Esc", "Back"),
        ],
    ),
    "CharacterScreen": (
        "Character / staff",
        [
            ("Click a title", "Open it"),
            ("☆ (click)", "Add or remove from favourites"),
            ("Esc", "Back"),
        ],
    ),
    "StudioScreen": (
        "Studio",
        [
            ("Enter / click", "Open the anime"),
            ("Tab", "Move between titles"),
            ("Load more", "Show the next titles"),
            ("Esc", "Back"),
        ],
    ),
    "SettingsScreen": (
        "Settings",
        [
            ("Help", "Guide to how Anilixy works (anime, manga, light novels...)"),
            ("Tab", "Move between settings"),
            ("Enter", "Press a button / confirm the delay"),
            ("Quality / Dub", "Options passed to ani-cli when you watch"),
            ("Notifications", "Desktop alerts for new episodes and chapters (every 30 min)"),
            ("Clear downloads", "Delete manga chapters saved offline (O in the reader)"),
            ("Esc", "Back"),
        ],
    ),
    "GuideScreen": (
        "Guide",
        [
            ("1 – 5", "Switch tab"),
            ("↑ / ↓", "Scroll"),
            ("Esc", "Close"),
        ],
    ),
    "ThemeScreen": (
        "Theme",
        [
            ("↑ / ↓", "Preview a theme"),
            ("Enter", "Confirm"),
            ("Esc", "Cancel (keeps the previous theme)"),
        ],
    ),
    "AnimationScreen": (
        "Animation",
        [
            ("↑ / ↓", "Preview an animation"),
            ("Enter", "Confirm"),
            ("Esc", "Cancel (keeps the previous animation)"),
        ],
    ),
    "LightNovelReaderScreen": (
        "Light novel reader",
        [
            ("← / →", "Previous / next chapter (at the ends: previous / next volume)"),
            ("↑ / ↓  PgUp / PgDn", "Scroll"),
            ("C", "Start / pause the AniList chapter count (turns auto-detect off)"),
            ("R", "Reset the count of this volume (back to auto-detect)"),
            ("F", "Pick another volume with fzf"),
            ("L", "Chapter menu"),
            ("W / S", "Zoom images in / out"),
            ("Esc / Q", "Close the reader"),
        ],
    ),
    "MangaReaderScreen": (
        "Manga reader",
        [
            ("← / →", "Previous / next page (ends: chapter)"),
            ("D", "Two pages side by side (book mode)"),
            ("F", "Shift the two-page pairing by one page"),
            ("L", "Chapter menu (or click Chapters)"),
            ("O", "Save this chapter offline"),
            ("Shift+O", "Choose chapters to save offline"),
            ("↑ / ↓", "Scroll"),
            ("PgUp / PgDn / Space", "Scroll a screen"),
            ("Home / End", "Top / bottom"),
            ("P / N", "Previous / next chapter"),
            ("C", "Switch page / webtoon mode"),
            ("W / S", "Zoom in / out"),
            ("0", "Reset zoom"),
            ("Esc / Q", "Close the reader (your page is saved)"),
        ],
    ),
}

GENERAL = [("?", "Show or close this help"), ("Ctrl+Q", "Quit Anilixy")]


def help_for(screen):
    for cls in type(screen).__mro__:
        if cls.__name__ in HELP:
            title, rows = HELP[cls.__name__]
            return title, list(rows) + [("", "")] + GENERAL
    return None
