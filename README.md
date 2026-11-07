# anilixy

```
 █████╗ ███╗   ██╗██╗██╗     ██╗██╗  ██╗██╗   ██╗
██╔══██╗████╗  ██║██║██║     ██║╚██╗██╔╝╚██╗ ██╔╝
███████║██╔██╗ ██║██║██║     ██║ ╚███╔╝  ╚████╔╝
██╔══██║██║╚██╗██║██║██║     ██║ ██╔██╗   ╚██╔╝
██║  ██║██║ ╚████║██║███████╗██║██╔╝ ██╗   ██║
╚═╝  ╚═╝╚═╝  ╚═══╝╚═╝╚══════╝╚═╝╚═╝  ╚═╝   ╚═╝
```

A terminal app to **watch anime, read manga and read light novels**, with your
progress synced to [AniList](https://anilist.co). Built with
[Textual](https://textual.textualize.io), playing anime through
[ani-cli](https://github.com/pystardust/ani-cli) and mpv.

https://github.com/user-attachments/assets/e8abbd41-564e-465b-9813-773e46e14665

## Features

- **Anime**: press *Watch* and it starts at the next episode after your AniList
  progress. It resumes episodes you stopped halfway, autoplays the next one and
  updates AniList as you watch. Video quality and dub can be set in Settings.
- **Manga**: a reader inside the terminal (page, two-page and webtoon modes,
  zoom). Chapters come from WeebCentral, with MangaTown as a fallback. You can
  save chapters to read offline.
- **Light novels**: an EPUB/PDF reader that counts chapters for your AniList
  progress. If a book isn't in your folder, it lists the volumes on JNovels so
  you can download them.
- **New episodes and chapters**: it checks in the background and tells you, in
  the app and with a desktop notification (on Windows, only in the app).
- **AniList**: search anime, manga, characters, staff and studios. Browse your
  profile, lists, favourites and stats, and edit list entries.
- **Extras**: themes, animated backgrounds, Discord Rich Presence and a guest
  mode that works without an account.

## Requirements

- Linux, macOS or Windows 10/11
- Python 3.10+ (on Windows, 64-bit Python 3.10 to 3.14: the `reliq` dependency
  has no Windows packages for newer versions yet)
- [mpv](https://mpv.io), [ani-cli](https://github.com/pystardust/ani-cli),
  [fzf](https://github.com/junegunn/fzf) and git (on Windows,
  [Git for Windows](https://gitforwindows.org), since ani-cli runs in its bash)
- For sharp covers and manga pages, a terminal with the Kitty graphics
  protocol or sixel (kitty, Ghostty, WezTerm, Konsole, foot…). Other
  terminals fall back to blocky, low-resolution images, and the manga reader
  can't show pages at all. On Windows, use Windows Terminal 1.22+ or a
  [WezTerm](https://wezterm.org) nightly build: stable WezTerm's console layer
  drops image data before it reaches the terminal.

## Installation

```bash
git clone https://github.com/lexviy/anilixy.git
cd anilixy
bash install.sh
```

`install.sh` does three things:

1. Installs the system dependencies (mpv, fzf, git, Python) with your package
   manager. It supports apt, dnf, pacman, zypper, xbps, emerge and Homebrew.
   On Fedora, mpv comes from [RPM Fusion](https://rpmfusion.org) (and on
   Alma/Rocky/RHEL also from EPEL); the script asks before enabling them.
2. Installs ani-cli if it is missing (pinned to a tested release; use
   `ANI_CLI_REF=v5.0 bash install.sh` to pick another).
3. Installs anilixy with [pipx](https://pipx.pypa.io). If pipx isn't
   available, it uses a virtual environment in `~/.local/share/anilixy/venv`.
   It also asks whether to add PDF support for light novels.
4. Adds anilixy to your app launcher (rofi, wofi, GNOME, KDE and others).

Then run:

```bash
anilixy
```

### Windows

The easiest way, with no Python needed: download
`anilixy-windows-x64.zip` from the
[releases page](https://github.com/lexviy/anilixy/releases) and extract it.
Run `install-dependencies.cmd` once to get Git for Windows, mpv, fzf and
ani-cli, then double-click `anilixy.exe`. It opens in its own window, using a
portable copy of Windows Terminal that comes in the zip and leaves any Terminal
you have installed alone.

To install from source instead, in PowerShell:

```powershell
git clone https://github.com/lexviy/anilixy.git
cd anilixy
powershell -ExecutionPolicy Bypass -File install.ps1
```

`install.ps1` installs what is missing with [Scoop](https://scoop.sh) or winget
(Git for Windows, mpv, fzf), fetches ani-cli into `%LOCALAPPDATA%\anilixy\bin`
and installs anilixy with pipx. A 64-bit Python 3.10 to 3.14 must already be
installed; it can sit beside newer versions.

Run `anilixy` from Windows Terminal, in PowerShell or cmd. Avoid the
Git Bash window (mintty), which has
[known problems with fzf](https://github.com/pystardust/ani-cli#windows-known-problems-and-solutions).

### Manual installation

anilixy is on [PyPI](https://pypi.org/project/anilixy/):

```bash
pipx install anilixy
```

pipx only installs the Python part. Install mpv, ani-cli, fzf and git yourself
(see [Requirements](#requirements)).

### PDF light novels (optional)

EPUB works out of the box. `install.sh` offers to add PyMuPDF for PDFs; to add
it later by hand:

```bash
pipx inject anilixy pymupdf
# or, without pipx:  pip install "anilixy[pdf]"
```

## Updating

From the folder you cloned:

```bash
git pull
bash install.sh
```

`install.sh` reinstalls anilixy from the updated code. Your login, settings,
progress and offline manga are kept, and so is PDF support if you had it.

ani-cli is updated separately:

```bash
ani-cli -U
```

If you installed from PyPI with pipx, use `pipx upgrade anilixy` instead.

## First run: logging in to AniList

1. Go to <https://anilist.co/settings/developer> and create a new client.
   Set the **Redirect URL** to `https://anilist.co/api/v2/oauth/pin`.
2. In anilixy, paste the **Client ID** and press *Token link*. Authorize the
   app in the browser.
3. Copy the token AniList shows you, paste it into anilixy and press *Login*.

You can also press **Guest** to use the app without an account. Progress is
then kept only on your computer.

## Using it

Press **`?`** on any screen to see its keys, or open **Settings → Help** for a
full guide with tabs for anime, manga and light novels.

| Where | Keys |
|---|---|
| Everywhere | `?` help · `Ctrl+Q` quit · `Esc` back |
| Title pages | `1`–`4` tabs · click ☆ to favourite |
| Manga reader | `←/→` pages · `P/N` chapters · `L` chapter menu · `C` webtoon mode · `D` two pages · `W/S` zoom · `O` save offline (`Shift+O`: 5 chapters) |
| Light novel reader | `←/→` chapters · `L` chapter menu · `F` pick a volume · `C`/`R` start/reset the chapter count |
| mpv (anime) | `N/P` next / previous episode |

### Light novels folder

Light novels are read from a folder, which is `~/Downloads/anilixy` by
default. You can change it in Settings. Files are matched by title, so keep
the series name in the file name, for example
`Classroom of the Elite Vol. 1.epub`. Books that aren't on AniList can be
added in **Custom light novels**.

### Discord Rich Presence

It works out of the box when the Discord desktop app is running, and you can
turn it off in Settings. To show your own Discord application instead, set
`ANILIXY_DISCORD_CLIENT_ID` or write `{"client_id": "..."}` to
`discord.json` in the configuration folder (see below).

## Where your data lives

| Path | What |
|---|---|
| `~/.config/anilixy/` | login token, settings, progress, saved manga sources |
| `~/.cache/anilixy/` | covers, cached AniList pages, `anilixy.log` |
| `~/.local/share/anilixy/manga/` | manga chapters saved offline |

On Windows:

| Path | What |
|---|---|
| `%APPDATA%\anilixy\` | login token, settings, progress, saved manga sources |
| `%LOCALAPPDATA%\anilixy\cache\` | covers, cached AniList pages, `anilixy.log` |
| `%LOCALAPPDATA%\anilixy\manga\` | manga chapters saved offline |

*Settings → Clean cache* empties the cache, and *Clear downloads* deletes the
offline chapters.

## Troubleshooting

- **Something failed silently?** Look at `~/.cache/anilixy/anilixy.log`. To
  also log the errors that the app ignores on purpose, run
  `ANILIXY_DEBUG=1 anilixy` (in PowerShell: `$env:ANILIXY_DEBUG=1; anilixy`).
- **Blurry or blocky images**: your terminal doesn't support the Kitty
  graphics protocol or sixel, so anilixy falls back to text blocks. Try kitty,
  Ghostty, WezTerm, Konsole or foot.
- **Pixelated covers or blank manga pages on Windows**: the terminal or its
  console layer doesn't pass images through. Use Windows Terminal 1.22+ (from
  the Microsoft Store or `winget install Microsoft.WindowsTerminal`) or
  `winget install wez.wezterm.nightly`.
- **`Failed to build reliq` on Windows**: your Python is too new or not 64-bit.
  Install 64-bit Python 3.14, then run `install.ps1` again.
- **"ani-cli or Git Bash was not found" on Windows**: anilixy needs
  `bash.exe` from Git for Windows (WSL's bash doesn't work) and the `ani-cli`
  script, on `PATH` or in `%LOCALAPPDATA%\anilixy\bin`.
- **Wrong series when watching or reading**: use *Reset source* on the anime
  page, or *Source* on the manga page, to pick it again.

## Uninstalling

```bash
bash uninstall.sh
```

It asks before removing each part: anilixy, ani-cli, manga chapters saved
offline (`~/.local/share/anilixy/manga`), the cache with covers and logs
(`~/.cache/anilixy`) and your configuration (`~/.config/anilixy`: login,
settings, progress and history). System packages are never removed.

On Windows, run `pipx uninstall anilixy`, then delete `%APPDATA%\anilixy` and
`%LOCALAPPDATA%\anilixy`. Deleting them also removes your login, progress and
offline manga.

## Project layout

```
src/anilixy/
├── main.py, app.py, anilixy.tcss   entry point, Textual app and styles
├── anime/      anime page, Keep watching, ani-cli player, resume and progress
├── manga/      manga page, reader, offline chapters, new chapters, sources/
├── novels/     light novel screens, EPUB/PDF reader, JNovels, custom novels
├── anilist/    AniList API (with disk cache), login, profile, formatting
├── ui/         shared screens (menu, search, settings, guide…) and widgets
└── core/       storage paths, settings, logging, update checks, Discord RPC, IPC
```

## Disclaimer

anilixy doesn't host any content. It is a client for AniList, and it uses
ani-cli and third-party websites (WeebCentral, MangaTown, JNovels) for the
anime, manga and light novels. Those sites decide what is available, and you
are responsible for following the laws of your country. Support the official
releases when you can.

## License

anilixy is free software, licensed under the
[GNU Affero General Public License v3.0 or later](LICENSE).

It depends on libraries under the same family of licenses: EbookLib (AGPL-3.0),
PyMuPDF (AGPL-3.0, optional) and weebcentral (GPL-3.0). The AGPL is compatible
with all of them.
