import logging
import re
from urllib.parse import quote

from weebcentral import Api

log = logging.getLogger(__name__)


class WeebCentral:
    def __init__(self):
        self.api = Api(
            wait=1.2
        )

    def search(self, query: str) -> list[dict]:
        results = []
        try:
            url = f"https://weebcentral.com/search?text={quote(query)}"
            for page in self.api.get_search(url):
                for item in page:
                    results.append(
                        {
                            "id": item.get("id"),
                            "title": item.get("name") or "?",
                            "url": item.get("link"),
                        }
                    )
        except Exception:
            log.warning("WeebCentral request failed", exc_info=True)
        return results

    def get_chapters(self, series_url: str) -> list[dict]:
        try:
            series = self.api.get_series(series_url, comments=False, chapters=True)
            chapters = series.get("chapters") or []

            def num(c):
                m = re.search(r"(\d+(?:\.\d+)?)", c.get("name", ""))
                return float(m.group(1)) if m else 0.0

            chapters.sort(key=num)
            return chapters
        except Exception:
            log.warning("WeebCentral request failed", exc_info=True)
            return []

    def get_pages(self, chapter_url: str) -> list[dict]:
        try:
            chapter = self.api.get_chapter(chapter_url, comments=False, images=True)
            images = chapter.get("images") or []
            return [{"index": i, "url": img} for i, img in enumerate(images)]
        except Exception:
            log.warning("WeebCentral request failed", exc_info=True)
            return []


weebcentral = WeebCentral()
