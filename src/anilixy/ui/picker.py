import shutil
import subprocess
from pathlib import Path

from anilixy.core.settings import load_ln_folder


def fzf_available() -> bool:
    return shutil.which("fzf") is not None


def fzf_pick(app, items, prompt="> ", multi=False, header=None):
    if not items or not fzf_available():
        return None
    values = {}
    lines = []
    for index, (label, value) in enumerate(items):
        key = str(index)
        values[key] = value
        clean = str(label).replace("\t", " ").replace("\n", " ")
        lines.append(f"{clean}\t{key}")
    command = ["fzf", "--reverse", "--cycle", "--delimiter=\t", "--with-nth=1", f"--prompt={prompt}"]
    if multi:
        command += ["--multi", "--bind=ctrl-a:select-all"]
        header = header or "Tab: select | Ctrl-A: all | Enter: confirm"
    if header:
        command.append(f"--header={header}")
    try:
        with app.suspend():
            proc = subprocess.run(
                command, input="\n".join(lines), capture_output=True, text=True
            )
    except Exception:
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    picked = [
        values[line.rsplit("\t", 1)[-1]]
        for line in proc.stdout.splitlines()
        if line.strip() and line.rsplit("\t", 1)[-1] in values
    ]
    if multi:
        return picked or None
    return picked[0] if picked else None


def path_items(paths):
    folder = load_ln_folder()
    items = []
    for path in paths:
        try:
            shown = str(Path(path).relative_to(folder))
        except ValueError:
            shown = Path(path).name
        items.append((shown, str(path)))
    return items


def pick_path(app, paths, prompt="Volume> "):
    return fzf_pick(app, path_items(paths), prompt)


def pick_paths(app, paths, prompt="Files> "):
    return fzf_pick(app, path_items(paths), prompt, multi=True)
