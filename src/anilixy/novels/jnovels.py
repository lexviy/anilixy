import os
import re
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from anilixy.core.settings import load_ln_folder

BASE_URL = "https://jnovels.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


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


def search(query: str) -> list[dict]:
    params = {"search": query, "per_page": 20}
    resp = requests.get(
        f"{BASE_URL}/wp-json/wp/v2/search", params=params, headers=HEADERS, timeout=10
    )
    resp.raise_for_status()
    items = resp.json()
    results = []
    for item in items:
        if item.get("type") != "post":
            continue
        title = item.get("title", "Unknown")
        title = BeautifulSoup(title, "html.parser").get_text()
        url = item.get("url")
        if "epub" in title.lower() and "[manga]" not in title.lower():
            results.append({"id": item.get("id"), "title": title, "url": url})
    return results


def original_post(post_url: str) -> str | None:
    resp = requests.get(post_url, headers=HEADERS, timeout=10)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    content = soup.select_one(".post-content") or soup
    for a in content.find_all("a", href=True):
        if "original post" in a.get_text(" ", strip=True).lower():
            href = a["href"]
            if href.startswith(BASE_URL):
                return href
    return None


def _base_title(title: str) -> str:
    t = title.lower()
    t = re.sub(r"^download\s+", "", t)
    t = re.sub(r"\b(all volumes|light novel|epubs?|pdf)\b", " ", t)
    t = re.sub(r"\b(volume|vol\.?)\s*[\d.]+.*$", " ", t)
    return re.sub(r"[^a-z0-9]+", "", t)


def find_work_page(title: str) -> str | None:
    results = search(title)
    if not results:
        return None
    wanted = _base_title(title)
    exact = [r for r in results if _base_title(r["title"]) == wanted]
    ranked = exact + [r for r in results if r not in exact]
    for result in ranked:
        if "all volumes" in result["title"].lower():
            return result["url"]
    first = ranked[0]["url"]
    try:
        return original_post(first) or first
    except Exception:
        return first


_NOT_DOWNLOAD = re.compile(
    r"jnovels\.com|adjust\.com|google\.com|apple\.com|facebook|x\.com|twitter|discord|patreon|ko-fi",
    re.I,
)
_DOWNLOAD_SUFFIX = re.compile(r"[\s—–\-]*download\s*$", re.I)


def get_volume_links(page_url: str) -> list[dict]:
    resp = requests.get(page_url, headers=HEADERS, timeout=10)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    content = soup.select_one(".post-content") or soup
    volumes = []
    seen = set()
    for a in content.find_all("a", href=True):
        href = a["href"].strip()
        if not href.startswith("http") or _NOT_DOWNLOAD.search(href) or href in seen:
            continue
        parent = a.find_parent(["li", "p", "h2", "h3", "h4", "td"])
        label = parent.get_text(" ", strip=True) if parent else ""
        label = _DOWNLOAD_SUFFIX.sub("", label).strip(" —–-")
        if not label or len(label) > 120:
            label = _DOWNLOAD_SUFFIX.sub("", a.get_text(" ", strip=True)).strip()
        if not label:
            continue
        seen.add(href)
        volumes.append({"title": re.sub(r"\s+", " ", label), "url": href})
    return volumes


def find_work(title: str):
    page = find_work_page(title)
    if not page:
        return None, []
    try:
        return page, get_volume_links(page)
    except Exception:
        return page, []
