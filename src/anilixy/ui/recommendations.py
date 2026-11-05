from concurrent.futures import ThreadPoolExecutor, as_completed

from rich.text import Text
from textual.containers import HorizontalScroll, Vertical
from textual.widgets import (
    Static,
)
from textual_image.widget import Image

from anilixy.ui.covers import fit_cover, safe_cover
from anilixy.ui.widgets import ClickLabel


class RecommendationsMixin:
    def fill_recommendations(self, recs) -> None:
        row = self.query_one("#recs-row", HorizontalScroll)
        row.remove_children()
        self.rec_images = {}
        if not recs:
            row.mount(Static("No recommendations"))
            return
        for index, rec in enumerate(recs):
            children = []
            if rec["cover_url"]:
                picture = Image(classes="rel-cover")
                self.rec_images[index] = picture
                children.append(picture)
            payload = {"kind": "media", "id": rec["id"]}
            children.append(
                ClickLabel(rec["title"], payload, classes="rel-title clickable")
            )
            children.append(Static(Text(rec["kind"]), classes="rec-kind"))
            row.mount(Vertical(*children, classes="rel-card"))

    def set_rec_cover(self, index, cover) -> None:
        picture = getattr(self, "rec_images", {}).get(index)
        if picture is not None and picture.is_attached:
            picture.image = fit_cover(cover, 12, 9)

    def load_rec_covers(self, recs) -> None:
        with ThreadPoolExecutor(max_workers=12) as pool:
            futures = {
                pool.submit(safe_cover, rec["cover_url"]): index
                for index, rec in enumerate(recs)
                if rec["cover_url"]
            }
            for future in as_completed(futures):
                cover = future.result()
                if cover is not None:
                    self.app.call_from_thread(
                        self.set_rec_cover, futures[future], cover
                    )
