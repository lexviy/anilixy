"""The light novel books in the user's folder."""

import os
import re
from pathlib import Path

from anilixy.core.settings import load_ln_folder

MAX_DEPTH = 2
BOOK_EXTENSIONS = (".epub", ".pdf")


def list_books(folder=None) -> list[Path]:
    folder = Path(folder) if folder else load_ln_folder()
    if not folder.is_dir():
        return []
    base = len(folder.parts)
    found = []
    for root, dirs, files in os.walk(folder):
        depth = len(Path(root).parts) - base
        if depth < MAX_DEPTH:
            dirs[:] = [d for d in dirs if not d.startswith(".")]
        else:
            dirs[:] = []
        for name in files:
            if name.lower().endswith(BOOK_EXTENSIONS):
                found.append(Path(root) / name)
    return found


def _natural_key(path: Path):
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", path.stem)]


def natural_key(path):
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", str(path))]


def get_local_volumes(title: str) -> list[Path]:
    safe_title = re.sub(r"[^a-zA-Z0-9\s]", "", title).lower()

    by_stem = {}
    for filepath in list_books():
        safe_filename = re.sub(r"[^a-zA-Z0-9\s]", "", filepath.stem).lower()
        if safe_title in safe_filename or safe_filename in safe_title:
            current = by_stem.get(filepath.stem)
            if current is None or (
                current.suffix.lower() != ".epub" and filepath.suffix.lower() == ".epub"
            ):
                by_stem[filepath.stem] = filepath

    return sorted(by_stem.values(), key=_natural_key)
