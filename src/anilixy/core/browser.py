import shutil
import subprocess
import webbrowser


def open_url(url: str) -> bool:
    opener = shutil.which("xdg-open")

    if opener:
        subprocess.Popen(
            [opener, url],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return True

    return webbrowser.open(url)
