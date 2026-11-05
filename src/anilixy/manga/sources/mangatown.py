import logging
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote, urljoin

import requests
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

BASE_URL = "https://www.mangatown.com/"
REFERER = BASE_URL
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
    ),
    "Referer": REFERER,
}

IMAGE_RE = re.compile(r'<img[^>]*\bsrc="([^"]+)"[^>]*\bid="image"|<img[^>]*\bid="image"[^>]*\bsrc="([^"]+)"')
TOTAL_RE = re.compile(r"var\s+total_pages\s*=\s*(\d+)")
CHAPTER_RE = re.compile(r"/c(\d+(?:\.\d+)?)/?$")


def absolute(url):
    if url.startswith("//"):
        return "https:" + url
    return urljoin(BASE_URL, url)


def chapter_number(url):
    match = CHAPTER_RE.search(url)
    if not match:
        return None
    return float(match.group(1))


class MangaTown:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def get(self, url):
        resp = self.session.get(url, timeout=15)
        resp.raise_for_status()
        return resp.text

    def search(self, query: str) -> list[dict]:
        try:
            html = self.get(f"{BASE_URL}search?name={quote(query)}")
            soup = BeautifulSoup(html, "html.parser")
            results = []
            seen = set()
            for link in soup.select("ul.manga_pic_list a.manga_cover"):
                href = link.get("href")
                if not href or href in seen:
                    continue
                seen.add(href)
                results.append(
                    {
                        "title": (link.get("title") or "?").strip(),
                        "url": absolute(href),
                    }
                )
            return results
        except Exception:
            log.warning("MangaTown request failed", exc_info=True)
            return []

    def get_chapters(self, series_url: str) -> list[dict]:
        try:
            soup = BeautifulSoup(self.get(series_url), "html.parser")
            chapters = []
            seen = set()
            for link in soup.select("ul.chapter_list a[href]"):
                url = absolute(link["href"])
                number = chapter_number(url.rstrip("/") + "/")
                if number is None or url in seen:
                    continue
                seen.add(url)
                chapters.append(
                    {"name": f"Chapter {number:g}", "link": url, "number": number}
                )
            chapters.sort(key=lambda c: c["number"])
            return chapters
        except Exception:
            log.warning("MangaTown request failed", exc_info=True)
            return []

    def page_image(self, url):
        match = IMAGE_RE.search(self.get(url))
        if not match:
            return None
        return absolute(match.group(1) or match.group(2))

    def get_pages(self, chapter_url: str) -> list[dict]:
        try:
            base = chapter_url.rstrip("/") + "/"
            html = self.get(base)
            total = TOTAL_RE.search(html)
            total = int(total.group(1)) if total else 1
            first = IMAGE_RE.search(html)
            images = [absolute(first.group(1) or first.group(2)) if first else None]

            def grab(page):
                for _ in range(2):
                    try:
                        return self.page_image(f"{base}{page}.html")
                    except Exception:
                        continue
                return None

            if total > 1:
                with ThreadPoolExecutor(max_workers=6) as pool:
                    images.extend(pool.map(grab, range(2, total + 1)))
            images = [img for img in images if img]
            return [{"index": i, "url": img} for i, img in enumerate(images)]
        except Exception:
            log.warning("MangaTown request failed", exc_info=True)
            return []


mangatown = MangaTown()
