import math
import random
import time
from functools import lru_cache

from rich.segment import Segment
from rich.style import Style
from textual.color import Color
from textual.screen import ModalScreen
from textual.strip import Strip
from textual.widget import Widget

KINDS = [
    "off",
    "rain",
    "snow",
    "stars",
    "sakura",
    "fireflies",
    "waves",
    "clouds",
    "lilies",
]

FPS = 15


@lru_cache(maxsize=512)
def fade(color: str, background: str, amount: float) -> str:
    return Color.parse(color).blend(Color.parse(background), amount).hex


@lru_cache(maxsize=512)
def mix(color: str, other: str, amount: float) -> str:
    return Color.parse(color).blend(Color.parse(other), amount).hex


def make_palette(variables: dict) -> dict:
    bg = variables["background"]
    fg = variables["foreground"]
    return {
        "bg": bg,
        "fg": fg,
        "primary": variables["primary"],
        "secondary": variables["secondary"],
        "accent": variables["accent"],
        "warning": variables.get("warning", variables["accent"]),
        "dim": fade(fg, bg, 0.45),
        "faint": fade(fg, bg, 0.7),
    }


class Canvas:

    def __init__(self, width: int, height: int):
        self.w = width
        self.h = height
        self.flash = 0.0
        self.chars = [[" "] * width for _ in range(height)]
        self.colors = [[None] * width for _ in range(height)]

    def clear(self):
        self.flash = 0.0
        for y in range(self.h):
            row = self.chars[y]
            colors = self.colors[y]
            for x in range(self.w):
                row[x] = " "
                colors[x] = None

    def put(self, x, y, ch, color):
        x = int(round(x))
        y = int(round(y))
        if 0 <= x < self.w and 0 <= y < self.h and ch != " ":
            self.chars[y][x] = ch
            self.colors[y][x] = color


class Rain:

    def __init__(self, w, h, pal, rng=None):
        self.rng = rng or random.Random()
        self.pal = pal
        self.t = 0.0
        self.resize(w, h)

    def set_palette(self, pal):
        self.pal = pal

    def resize(self, w, h):
        self.w, self.h = w, h
        count = max(40, int(w * h * 0.03))
        self.drops = [self._drop(anywhere=True) for _ in range(count)]
        self.splashes = []
        self.bolt = None
        self.flash = 0.0
        self.next_bolt = self.rng.uniform(6, 14)

    def _drop(self, anywhere=False):
        layer = self.rng.choices([0, 1, 2], weights=[5, 3, 2])[0]
        speed = [
            self.rng.uniform(13, 20),
            self.rng.uniform(27, 37),
            self.rng.uniform(45, 60),
        ][layer]
        return {
            "x": self.rng.uniform(-self.h * 0.6, self.w + self.h * 0.2),
            "y": self.rng.uniform(0, self.h) if anywhere else self.rng.uniform(-self.h * 0.35, 0),
            "speed": speed,
            "layer": layer,
        }

    def wind(self):
        return -0.2 + 0.42 * math.sin(self.t * 0.28) + 0.08 * math.sin(self.t * 0.9 + 1.0)

    def _make_bolt(self):
        if self.rng.random() < 0.5:
            x = self.rng.uniform(self.w * 0.08, self.w * 0.3)
        else:
            x = self.rng.uniform(self.w * 0.7, self.w * 0.92)
        cells = []
        end = int(self.h * self.rng.uniform(0.65, 0.85))
        direction = 0
        for y in range(end):
            if self.rng.random() < 0.55:
                direction = self.rng.choice([-1, 0, 1])
            x += direction
            ch = "\\" if direction > 0 else "/" if direction < 0 else "|"
            cells.append((x, y, ch))
            if self.rng.random() < 0.12:
                side = self.rng.choice([-1, 1])
                for k in range(1, self.rng.randint(3, 6)):
                    cells.append((x + side * k, y + k // 2, "\\" if side > 0 else "/"))
        return cells

    def step(self, dt):
        self.t += dt
        wind = self.wind()
        ground = self.h - 1

        for d in self.drops:
            d["y"] += d["speed"] * dt
            d["x"] += wind * d["speed"] * dt
            if d["y"] >= ground:
                chance = (0.15, 0.35, 0.6)[d["layer"]]
                if len(self.splashes) < 80 and self.rng.random() < chance:
                    self.splashes.append(
                        {"x": d["x"], "age": 0.0, "layer": d["layer"]}
                    )
                d.update(self._drop())

        for s in self.splashes:
            s["age"] += dt
        self.splashes = [s for s in self.splashes if s["age"] < 0.45]

        self.next_bolt -= dt
        if self.bolt is None and self.next_bolt <= 0:
            self.bolt = {"cells": self._make_bolt(), "age": 0.0}
            self.next_bolt = self.rng.uniform(8, 18)

        self.flash = 0.0
        if self.bolt is not None:
            self.bolt["age"] += dt
            age = self.bolt["age"]
            if age > 0.4:
                self.bolt = None
            elif age < 0.08:
                self.flash = 1.0
            elif age < 0.15:
                self.flash = 0.2
            elif age < 0.24:
                self.flash = 0.75
            else:
                self.flash = 0.3

    def draw(self, canvas):
        pal = self.pal
        wind = self.wind()
        bright = self.flash > 0.5
        colors = [
            fade(pal["secondary"], pal["bg"], 0.62),
            fade(pal["secondary"], pal["bg"], 0.3),
            pal["fg"] if bright else pal["secondary"],
        ]
        if bright:
            colors[0] = fade(pal["dim"], pal["bg"], 0.45)
            colors[1] = pal["dim"]

        lean = "/" if wind < -0.08 else "\\" if wind > 0.08 else "|"
        ground = self.h - 1

        shimmer = int(self.t * 3)
        for x in range(self.w):
            if (x * 5 + shimmer) % 17 == 0:
                canvas.put(x, ground, "~", colors[0])

        for d in self.drops:
            layer = d["layer"]
            glyph = lean if layer else ("'" if lean != "|" else ".")
            for k in range(layer + 1):
                color = colors[max(0, layer - k)]
                canvas.put(d["x"] - wind * k, d["y"] - k, glyph, color)

        for s in self.splashes:
            x = int(round(s["x"]))
            age = s["age"]
            if age < 0.09:
                canvas.put(x, ground - 1, "'", colors[2])
                canvas.put(x, ground, ".", colors[2])
            elif age < 0.2:
                canvas.put(x - 1, ground - 1, "'", colors[2])
                canvas.put(x + 1, ground - 1, "'", colors[2])
                canvas.put(x, ground, "o", colors[2])
            elif age < 0.32:
                canvas.put(x - 2, ground, ".", colors[1])
                canvas.put(x + 2, ground, ".", colors[1])
                canvas.put(x - 1, ground - 1, "'", colors[1])
                canvas.put(x + 1, ground - 1, "'", colors[1])
            else:
                canvas.put(x - 3, ground, ".", colors[0])
                canvas.put(x + 3, ground, ".", colors[0])

        if self.bolt is not None:
            for x, y, ch in self.bolt["cells"]:
                canvas.put(x, y, ch, pal["fg"])
        canvas.flash = self.flash


class Snow:

    def __init__(self, w, h, pal, rng=None):
        self.rng = rng or random.Random()
        self.pal = pal
        self.t = 0.0
        self.gust = 0.0
        self.resize(w, h)

    def set_palette(self, pal):
        self.pal = pal

    def resize(self, w, h):
        self.w, self.h = w, h
        p1 = self.rng.uniform(0, math.tau)
        p2 = self.rng.uniform(0, math.tau)
        p3 = self.rng.uniform(0, math.tau)
        self.ground = []
        for x in range(w):
            edge = 0.9 * (abs(x - w / 2) / max(1, w / 2)) ** 3
            g = (
                1.2
                + edge
                + 0.9 * math.sin(x * 0.07 + p1)
                + 0.5 * math.sin(x * 0.23 + p2)
                + 0.25 * math.sin(x * 0.61 + p3)
            )
            self.ground.append(max(1, min(4, int(round(g)))))
        count = max(50, int(w * h * 0.03))
        self.flakes = [self._flake(anywhere=True) for _ in range(count)]
        self.sparkles = []

    def _flake(self, anywhere=False):
        layer = self.rng.choices([0, 1, 2], weights=[4, 3, 2])[0]
        return {
            "layer": layer,
            "x": self.rng.uniform(0, self.w),
            "y": self.rng.uniform(0, self.h) if anywhere else self.rng.uniform(-3, 0),
            "speed": [self.rng.uniform(2, 3.2), self.rng.uniform(4, 6), self.rng.uniform(7, 10)][layer],
            "amp": self.rng.uniform(0.4, 2.4),
            "freq": self.rng.uniform(0.5, 1.5),
            "phase": self.rng.uniform(0, 6.28),
            "ch": [".", self.rng.choice([".", "*"]), self.rng.choice(["*", "+", "o"])][layer],
        }

    def wind(self):
        return 1.2 * math.sin(self.t * 0.22) + self.gust

    def step(self, dt):
        self.t += dt
        self.gust *= math.exp(-dt * 0.9)
        if self.rng.random() < 0.12 * dt:
            self.gust = self.rng.uniform(-3.5, 3.5)

        wind = self.wind()
        for f in self.flakes:
            f["y"] += f["speed"] * dt
            f["x"] = (f["x"] + wind * (0.6 + 0.5 * f["layer"]) * dt) % self.w
            column = int(f["x"]) % self.w
            if f["y"] >= self.h - self.ground[column]:
                f.update(self._flake())

        if self.rng.random() < 3.5 * dt:
            if self.rng.random() < 0.75:
                x = self.rng.randrange(self.w)
                y = self.h - self.ground[x] - 1
            else:
                x = self.rng.randrange(self.w)
                y = self.rng.randrange(max(1, self.h - 2))
            if y >= 0:
                self.sparkles.append({"x": x, "y": y, "age": 0.0})
        for s in self.sparkles:
            s["age"] += dt
        self.sparkles = [s for s in self.sparkles if s["age"] < 0.7]

    def draw(self, canvas):
        pal = self.pal
        colors = [pal["faint"], pal["dim"], pal["fg"]]

        for x in range(self.w):
            top = self.h - self.ground[x]
            canvas.put(x, top, "~" if (x // 3) % 2 else ".", pal["dim"])
            if top + 1 < self.h:
                canvas.put(x, top + 1, ":" if (x + top) % 3 else ".", pal["faint"])
            for y in range(top + 2, self.h):
                canvas.put(x, y, ":" if (x + y) % 2 else ".", pal["faint"])

        for s in self.sparkles:
            x, y, age = s["x"], s["y"], s["age"]
            if age < 0.28:
                canvas.put(x, y, "*", pal["fg"])
                canvas.put(x - 1, y, "-", pal["dim"])
                canvas.put(x + 1, y, "-", pal["dim"])
            elif age < 0.5:
                canvas.put(x, y, "+", pal["dim"])
            else:
                canvas.put(x, y, ".", pal["faint"])

        for f in self.flakes:
            x = f["x"] + f["amp"] * math.sin(f["phase"] + f["freq"] * self.t)
            canvas.put(x, f["y"], f["ch"], colors[f["layer"]])


class Stars:

    TRAIL = 14

    def __init__(self, w, h, pal, rng=None):
        self.rng = rng or random.Random()
        self.pal = pal
        self.t = 0.0
        self.resize(w, h)

    def set_palette(self, pal):
        self.pal = pal

    def resize(self, w, h):
        self.w, self.h = w, h
        count = max(20, int(w * h * 0.02))
        self.stars = [
            {
                "x": self.rng.randrange(w),
                "y": self.rng.randrange(h),
                "phase": self.rng.uniform(0, math.tau),
                "freq": self.rng.uniform(0.5, 2.4),
                "shade": self.rng.choices([0, 1, 2], weights=[5, 3, 2])[0],
            }
            for _ in range(count)
        ]
        self.dust = []
        for _ in range(max(40, int(w * h * 0.012))):
            x = self.rng.randrange(w)
            center = h * 0.15 + x * (h * 0.55 / max(1, w))
            y = int(center + self.rng.gauss(0, max(1.0, h * 0.09)))
            if 0 <= y < h:
                self.dust.append(
                    {
                        "x": x,
                        "y": y,
                        "phase": self.rng.uniform(0, math.tau),
                        "freq": self.rng.uniform(0.2, 0.8),
                    }
                )
        big = max(3, int(w * h / 900))
        self.big = [
            {
                "x": self.rng.randrange(3, max(4, w - 3)),
                "y": self.rng.randrange(2, max(3, h - 2)),
                "phase": self.rng.uniform(0, math.tau),
            }
            for _ in range(big)
        ]
        self.shooting = []
        self.next_shot = self.rng.uniform(0.5, 2)

    def step(self, dt):
        self.t += dt
        self.next_shot -= dt
        if self.next_shot <= 0 and len(self.shooting) < 4:
            speed = self.rng.uniform(45, 75)
            self.shooting.append(
                {
                    "x0": self.rng.uniform(self.w * 0.25, self.w * 1.1),
                    "y0": self.rng.uniform(-2, self.h * 0.35),
                    "vx": -speed,
                    "vy": speed * 0.5,
                    "ay": self.rng.uniform(0.0, 2.5),
                    "age": 0.0,
                    "big": self.rng.random() < 0.2,
                }
            )
            self.next_shot = self.rng.uniform(0.8, 2.8)

        for s in self.shooting:
            s["age"] += dt
        self.shooting = [
            s
            for s in self.shooting
            if self._shot_pos(s, s["age"])[0] > -self.TRAIL
            and self._shot_pos(s, s["age"])[1] < self.h + 5
        ]

    @staticmethod
    def _shot_pos(s, age):
        x = s["x0"] + s["vx"] * age
        y = s["y0"] + s["vy"] * age + 0.5 * s["ay"] * age * age
        return x, y

    def draw(self, canvas):
        pal = self.pal

        for d in self.dust:
            if math.sin(d["phase"] + d["freq"] * self.t) > 0.3:
                canvas.put(d["x"], d["y"], ".", pal["faint"])

        tints = [pal["faint"], pal["secondary"], pal["fg"]]
        amounts = (0.55, 0.3, 0.0)
        colors = [
            [fade(tint, pal["bg"], amount) for amount in amounts] for tint in tints
        ]
        chars = ["", ".", "+", "*"]
        for s in self.stars:
            level = int((0.5 + 0.5 * math.sin(s["phase"] + s["freq"] * self.t)) * 3.99)
            if level:
                canvas.put(s["x"], s["y"], chars[level], colors[s["shade"]][level - 1])

        for s in self.big:
            pulse = 0.5 + 0.5 * math.sin(s["phase"] + self.t * 1.3)
            x, y = s["x"], s["y"]
            canvas.put(x, y, "*", pal["fg"])
            if pulse > 0.35:
                canvas.put(x - 1, y, "-", pal["dim"])
                canvas.put(x + 1, y, "-", pal["dim"])
                canvas.put(x, y - 1, "'", pal["dim"])
                canvas.put(x, y + 1, "'", pal["dim"])
            if pulse > 0.8:
                canvas.put(x - 2, y, ".", pal["faint"])
                canvas.put(x + 2, y, ".", pal["faint"])
                canvas.put(x, y - 2, ".", pal["faint"])
                canvas.put(x, y + 2, ".", pal["faint"])

        trail = [
            (pal["fg"], None),
            (pal["fg"], "+"),
            (pal["accent"], None),
            (pal["accent"], None),
            (pal["secondary"], None),
            (pal["secondary"], None),
            (pal["dim"], "."),
            (pal["dim"], "."),
            (pal["dim"], "."),
            (pal["faint"], "."),
            (pal["faint"], "."),
            (pal["faint"], "'"),
            (pal["faint"], "'"),
            (pal["faint"], "'"),
        ]
        for s in self.shooting:
            for k in range(self.TRAIL):
                age = s["age"] - k * 0.018
                if age < 0:
                    continue
                x, y = self._shot_pos(s, age)
                color, special = trail[k]
                if k == 0:
                    ch = "@" if s["big"] else "*"
                else:
                    ch = special or "/"
                canvas.put(x, y, ch, color)
                if k == 0 and s["big"]:
                    canvas.put(x + 1, y, "-", pal["dim"])


class SakuraTree:

    BLOSSOM_GLYPHS = [("@", "*"), ("*", "o"), ("o", "*"), ("%", "&"), ("&", "%"), ("@", "@")]

    def __init__(self, side, w, h, rng):
        self.side = side
        self.h = h
        self.rng = rng
        self.ht = max(8, int(h * 0.8))
        self.base_y = h - 1
        self.base_x = -2 if side < 0 else w + 1
        self.toward = -side
        self.lean = max(4, min(16, int(w * 0.09)))
        self.reach = max(10, int(w * 0.14))
        self.amp = 3.0
        self.trunk = []
        self.branches = []
        self.blossoms = []
        self._build()

    def _center_x(self, i):
        t = i / self.ht
        return self.base_x + self.toward * int(round((t ** 1.4) * self.lean))

    def _build(self):
        rng = self.rng
        for i in range(self.ht):
            y = self.base_y - i
            cx = self._center_x(i)
            width = 1 + int(4 * (1 - i / self.ht) ** 1.2)
            for dx in range(-(width // 2), width - width // 2):
                edge = dx in (-(width // 2), width - width // 2 - 1) and width > 1
                ch = "|" if edge or width == 1 else rng.choice(["#", "#", "%"])
                self.trunk.append((cx + dx, y, ch, "edge" if edge or width == 1 else "bark"))

        centers = []
        for t, scale in [(0.30, 0.55), (0.45, 0.8), (0.58, 0.65), (0.72, 0.9), (0.86, 0.7)]:
            i0 = int(t * self.ht)
            x0, y0 = self._center_x(i0), self.base_y - i0
            length = int(self.reach * (0.35 + 0.65 * scale * (0.8 + 0.4 * rng.random())))
            slope = 0.25 + rng.random() * 0.45
            tip = (x0, y0)
            for k in range(length):
                x = x0 + self.toward * (k + 1)
                y = y0 - int(k * slope)
                rising = int((k + 1) * slope) > int(k * slope)
                ch = ("/" if self.toward > 0 else "\\") if rising else "_"
                self.branches.append((x, y, ch))
                tip = (x, y)
                if k == length // 2:
                    for j in range(1, 4):
                        self.branches.append(
                            (x + self.toward * j // 2, y - j, "\\" if self.toward > 0 else "/")
                        )
                    centers.append((x, y - 3))
            centers.append(tip)

        top_i = self.ht - 1
        centers.append((self._center_x(top_i) + self.toward * 2, self.base_y - top_i))

        cells = {}
        for cx, cy in centers:
            rx = min(13, int(rng.randint(6, 9) * max(1.0, self.reach / 16)))
            ry = rng.randint(2, 4)
            for dy in range(-ry, ry + 1):
                for dx in range(-rx, rx + 1):
                    norm = (dx / rx) ** 2 + (dy / ry) ** 2
                    if norm > 1:
                        continue
                    if rng.random() > 0.76 - 0.26 * norm:
                        continue
                    if norm < 0.55:
                        shade = rng.choice([0, 0, 1, 1, 2])
                    else:
                        shade = rng.choice([1, 2, 2])
                    cells[(cx + dx, cy + dy - 1)] = (
                        rng.choice(self.BLOSSOM_GLYPHS),
                        shade,
                        rng.uniform(0, math.tau),
                    )
        self.blossoms = [(x, y, g, c, p) for (x, y), (g, c, p) in cells.items()]

    def sway(self, y, wind):
        rel = max(0.0, min(1.0, (self.base_y - y) / self.ht))
        return int(round(wind * self.amp * rel ** 1.5))

    def draw(self, canvas, colors, wind, t):
        for x, y, ch, kind in self.trunk:
            canvas.put(x + self.sway(y, wind), y, ch, colors["edge"] if kind == "edge" else colors["bark"])
        for x, y, ch in self.branches:
            canvas.put(x + self.sway(y, wind), y, ch, colors["branch"])
        for x, y, glyphs, shade, phase in self.blossoms:
            glyph = glyphs[1] if math.sin(phase + t * 2) > 0.6 else glyphs[0]
            canvas.put(x + self.sway(y, wind), y, glyph, colors["pinks"][shade])

    def random_blossom(self, wind):
        x, y, *_ = self.rng.choice(self.blossoms)
        return x + self.sway(y, wind), y


class Sakura:

    BASE_PINKS = ["#f4a7c0", "#e87fa3", "#fbd3e0"]
    BASE_BARK = "#7a5545"
    BASE_BRANCH = "#8a6250"

    def __init__(self, w, h, pal, rng=None):
        self.rng = rng or random.Random()
        self.pal = pal
        self._colors = self._make_colors(pal)
        self.t = 0.0
        self.gust = 0.0
        self.resize(w, h)

    def set_palette(self, pal):
        self.pal = pal
        self._colors = self._make_colors(pal)

    def _make_colors(self, pal):
        bg = pal["bg"]
        fg = pal["fg"]
        light_theme = Color.parse(bg).brightness > 0.55

        if light_theme:
            pinks = [fade(p, fg, 0.35) for p in self.BASE_PINKS]
        else:
            pinks = [mix(p, pal["accent"], 0.12) for p in self.BASE_PINKS]

        petals = [
            [fade(p, bg, 0.45) for p in pinks],
            [fade(p, bg, 0.2) for p in pinks],
            pinks,
        ]

        bark = mix(self.BASE_BARK, pal["secondary"], 0.12)
        return {
            "pinks": pinks,
            "petals": petals,
            "bark": bark,
            "edge": fade(bark, bg, 0.22),
            "branch": mix(self.BASE_BRANCH, pal["secondary"], 0.12),
        }

    def resize(self, w, h):
        self.w, self.h = w, h
        self.trees = [SakuraTree(-1, w, h, self.rng), SakuraTree(1, w, h, self.rng)]
        self.petals = []
        self.landed = []
        self.spawn = 0.0

    def wind(self):
        return max(-1.0, min(1.0, 0.65 * math.sin(self.t * 0.7) + 0.35 * math.sin(self.t * 1.9 + 1.0) + self.gust))

    def step(self, dt):
        self.t += dt
        self.gust *= math.exp(-dt * 0.8)
        if self.rng.random() < 0.1 * dt:
            self.gust = self.rng.uniform(-0.8, 0.8)

        wind = self.wind()

        self.spawn += 14 * dt
        while self.spawn >= 1 and len(self.petals) < 200:
            self.spawn -= 1
            tree = self.rng.choice(self.trees)
            x, y = tree.random_blossom(wind)
            depth = self.rng.choices([0, 1, 2], weights=[3, 4, 3])[0]
            self.petals.append(
                {
                    "x": float(x),
                    "y": float(y),
                    "vy": self.rng.uniform(2.2, 3.2) * (0.7 + 0.35 * depth),
                    "phase": self.rng.uniform(0, math.tau),
                    "color": self.rng.choice([0, 0, 1, 2]),
                    "depth": depth,
                    "spin": self.rng.uniform(1.5, 3.5),
                }
            )
        self.spawn = min(self.spawn, 2)

        for p in self.petals:
            p["y"] += p["vy"] * dt
            sway = 1.2 + 0.4 * p["depth"]
            p["x"] += (
                wind * (3.5 + p["depth"])
                + math.sin(p["phase"] + self.t * (1.8 + 0.3 * p["depth"])) * sway
            ) * dt

        for p in self.petals:
            if p["y"] >= self.h - 1:
                if len(self.landed) < 100:
                    self.landed.append(
                        {
                            "x": p["x"],
                            "color": p["color"],
                            "depth": p["depth"],
                            "age": 0.0,
                        }
                    )
        self.petals = [p for p in self.petals if p["y"] < self.h - 1 and -10 < p["x"] < self.w + 10]

        for p in self.landed:
            p["age"] += dt
        self.landed = [p for p in self.landed if p["age"] < 4.0]

    def draw(self, canvas):
        wind = self.wind()
        for tree in self.trees:
            tree.draw(canvas, self._colors, wind, self.t)

        small = ["'", ",", ".", "`"]
        large = ["*", "~", "o", "~"]
        for p in self.petals:
            seq = large if p["depth"] == 2 else small
            ch = seq[int(self.t * p["spin"] + p["phase"]) % len(seq)]
            color = self._colors["petals"][p["depth"]][p["color"]]
            canvas.put(p["x"], p["y"], ch, color)

        for p in self.landed:
            color = self._colors["petals"][p["depth"]][p["color"]]
            if p["age"] >= 2.5:
                color = fade(color, self.pal["bg"], 0.6)
            canvas.put(p["x"], self.h - 1, ".", color)


class Fireflies:

    def __init__(self, w, h, pal, rng=None):
        self.rng = rng or random.Random()
        self.t = 0.0
        self.set_palette(pal)
        self.resize(w, h)

    def set_palette(self, pal):
        self.pal = pal
        bg = pal["bg"]
        base = pal["warning"]
        self._colors = [
            fade(base, bg, 0.55),
            fade(base, bg, 0.25),
            mix(base, pal["fg"], 0.45),
        ]
        self._grass_back = fade(pal["secondary"], bg, 0.72)
        self._grass_front = fade(pal["secondary"], bg, 0.5)
        self._grass_tip = mix(pal["secondary"], pal["fg"], 0.25)

    def resize(self, w, h):
        self.w, self.h = w, h

        max_height = max(1, min(4, h // 5))
        self.grass = []
        x = 0
        while x < w:
            if self.rng.random() < 0.72:
                base = x
                for _ in range(self.rng.randint(1, 3)):
                    bx = base + self.rng.randint(-1, 2)
                    if not 0 <= bx < w:
                        continue
                    height = self.rng.choices(
                        range(1, max_height + 1),
                        weights=[4, 4, 2, 1][:max_height],
                    )[0]
                    lean = self.rng.uniform(-0.8, 0.8)
                    if lean < -0.25:
                        tips = ["\\", "`"]
                    elif lean > 0.25:
                        tips = ["/", "'"]
                    else:
                        tips = ["'", ",", "`"]
                    self.grass.append(
                        {
                            "x": bx,
                            "height": height,
                            "phase": self.rng.uniform(0, math.tau),
                            "lean": lean,
                            "weight": self.rng.uniform(0.6, 1.2),
                            "tip": self.rng.choice(tips),
                        }
                    )
                x += self.rng.randint(2, 5)
            else:
                x += self.rng.randint(1, 3)

        count = max(18, int(w * h * 0.008))
        self.flies = [self._fly(anywhere=True) for _ in range(count)]

    def _fly(self, anywhere=False):
        return {
            "x": self.rng.uniform(0, self.w),
            "y": (
                self.rng.uniform(0, self.h * 0.9)
                if anywhere
                else self.rng.uniform(self.h * 0.7, self.h)
            ),
            "vx": self.rng.uniform(-1.3, 1.3),
            "vy": self.rng.uniform(-0.5, 0.5),
            "phase": self.rng.uniform(0, math.tau),
            "freq": self.rng.uniform(0.5, 1.5),
            "sway": self.rng.uniform(0.4, 1.0),
        }

    def step(self, dt):
        self.t += dt
        for f in self.flies:
            f["x"] += (f["vx"] + math.sin(self.t * 0.7 + f["phase"]) * f["sway"]) * dt
            f["y"] += (f["vy"] + math.cos(self.t * 0.5 + f["phase"]) * 0.25) * dt

            if f["x"] < 0:
                f["x"] = 0
                f["vx"] = abs(f["vx"])
            elif f["x"] > self.w - 1:
                f["x"] = self.w - 1
                f["vx"] = -abs(f["vx"])
            if f["y"] < 0:
                f["y"] = 0
                f["vy"] = abs(f["vy"])
            elif f["y"] > self.h - 2:
                f["y"] = self.h - 2
                f["vy"] = -abs(f["vy"])

    def draw(self, canvas):
        for g in sorted(self.grass, key=lambda blade: blade["height"]):
            height = g["height"]
            for level in range(height):
                progress = (level + 1) / height
                sway = (
                    math.sin(self.t * 1.1 + g["phase"] + level * 0.35)
                    * g["weight"]
                    * 1.1
                    * progress
                )
                x = g["x"] + g["lean"] * level + sway
                y = self.h - 1 - level

                if level == height - 1:
                    ch, color = g["tip"], self._grass_tip
                elif level == 0:
                    ch, color = "|", self._grass_back
                else:
                    ch = "," if (g["x"] + level) % 3 == 0 else "|"
                    color = self._grass_front if height >= 3 else self._grass_back
                canvas.put(x, y, ch, color)

        for f in self.flies:
            pulse = max(0.0, math.sin(f["phase"] + self.t * f["freq"]))
            if pulse < 0.08:
                continue
            if pulse < 0.35:
                color, ch = self._colors[0], "."
            elif pulse < 0.72:
                color, ch = self._colors[1], "+"
            else:
                color, ch = self._colors[2], "*"

            x, y = f["x"], f["y"]
            canvas.put(x, y, ch, color)
            if pulse > 0.8:
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    canvas.put(x + dx, y + dy, ".", self._colors[0])


class Waves:

    def __init__(self, w, h, pal, rng=None):
        self.rng = rng or random.Random()
        self.pal = pal
        self.t = 0.0
        self.set_palette(pal)
        self.resize(w, h)

    def set_palette(self, pal):
        self.pal = pal
        bg = pal["bg"]
        self._colors = [
            fade(pal["primary"], bg, 0.62),
            fade(pal["secondary"], bg, 0.48),
            fade(pal["secondary"], bg, 0.25),
            mix(pal["secondary"], pal["fg"], 0.35),
        ]
        self._foam = mix(pal["fg"], pal["secondary"], 0.5)
        self._stars = [
            fade(pal["fg"], bg, 0.72),
            fade(pal["fg"], bg, 0.45),
            mix(pal["fg"], pal["secondary"], 0.3),
        ]
        self._moon = [
            fade(pal["secondary"], bg, 0.72),
            mix(pal["secondary"], pal["fg"], 0.5),
            pal["fg"],
        ]

    def resize(self, w, h):
        self.w, self.h = w, h
        self.layers = []
        for i in range(4):
            self.layers.append(
                {
                    "base": h * (0.45 + 0.13 * i),
                    "amp": 1.0 + 0.45 * i,
                    "length": max(12.0, w * (0.22 + 0.08 * i)),
                    "speed": 0.55 + 0.22 * i,
                    "phase": self.rng.uniform(0, math.tau),
                    "shade": i,
                }
            )
        self.stars = [
            {
                "x": self.rng.randrange(w),
                "y": self.rng.randrange(max(1, int(h * 0.46))),
                "phase": self.rng.uniform(0, math.tau),
                "freq": self.rng.uniform(0.7, 2.0),
                "size": self.rng.choices([0, 1, 2], weights=[6, 3, 1])[0],
            }
            for _ in range(max(12, int(w * h * 0.006)))
        ]
        self.moon = None
        if w >= 24 and h >= 18:
            radius = max(3, min(6, h // 6))
            cx = max(radius + 1, min(int(w * 0.78), w - radius - 2))
            cy = max(
                radius + 1,
                min(int(h * 0.18), int(h * 0.45) - radius - 1),
            )
            self.moon = {"x": cx, "y": cy, "r": radius}
        self.sparks = [
            {
                "x": self.rng.uniform(0, w),
                "y": self.rng.uniform(h * 0.55, max(h * 0.55 + 1, h - 1)),
                "phase": self.rng.uniform(0, math.tau),
            }
            for _ in range(max(10, int(w * h * 0.004)))
        ]

    def step(self, dt):
        self.t += dt

    def _draw_stars(self, canvas):
        for star in self.stars:
            pulse = math.sin(star["phase"] + self.t * star["freq"])
            if pulse < -0.2:
                continue
            if star["size"] == 2 and pulse > 0.35:
                ch, color = "*", self._stars[2]
            elif star["size"] >= 1 and pulse > 0.1:
                ch, color = "+", self._stars[1]
            else:
                ch, color = ".", self._stars[0]

            x, y = star["x"], star["y"]
            canvas.put(x, y, ch, color)
            if star["size"] == 2 and pulse > 0.8:
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    canvas.put(x + dx, y + dy, ".", self._stars[0])

    def _draw_moon(self, canvas):
        moon = self.moon
        cx, cy, r = moon["x"], moon["y"], moon["r"]
        bite_x = r * 0.78
        for dy in range(-r - 1, r + 2):
            for dx in range(-r - 1, r + 2):
                outer = math.hypot(dx, dy)
                inner = math.hypot(dx - bite_x, dy)
                if outer <= r + 0.25:
                    if inner > r:
                        edge = outer > r - 1 or inner < r + 1
                        ch = "*" if edge else "@"
                        color = self._moon[2] if edge else self._moon[1]
                        canvas.put(cx + dx, cy + dy, ch, color)
                    elif outer > r - 0.9:
                        canvas.put(cx + dx, cy + dy, ".", self._moon[0])
                elif r + 0.25 < outer <= r + 1.4 and inner > r + 0.4:
                    canvas.put(cx + dx, cy + dy, ".", self._moon[0])

    def draw(self, canvas):
        self._draw_stars(canvas)
        if self.moon is not None:
            self._draw_moon(canvas)

        for i, layer in enumerate(self.layers):
            color = self._colors[layer["shade"]]
            for x in range(self.w):
                angle = (
                    x / layer["length"] * math.tau
                    + layer["phase"]
                    - self.t * layer["speed"]
                )
                y = (
                    layer["base"]
                    + layer["amp"] * math.sin(angle)
                    + 0.4 * math.sin(angle * 2.3 + layer["phase"])
                )
                crest = math.sin(angle)
                ch = "~" if crest > 0.35 else "-"
                canvas.put(x, y, ch, color)

                if crest > 0.75 and (x * 7 + i * 3 + int(self.t * 2)) % 9 == 0:
                    canvas.put(x, y - 1, "'", self._foam)
                elif crest < -0.75 and (x + i) % 13 == 0:
                    canvas.put(x, y + 1, ".", self._colors[max(0, i - 1)])

        if self.moon is not None:
            moon_x = int(self.moon["x"])
            for y in range(int(self.h * 0.55), self.h):
                x = moon_x + int(round(1.6 * math.sin(y * 0.6 + self.t * 1.7)))
                if (y + int(self.t * 4)) % 3 == 0:
                    canvas.put(x, y, "~", self._colors[1])
                elif (y + int(self.t * 3)) % 5 == 0:
                    canvas.put(x, y, ".", self._colors[0])

        for s in self.sparks:
            if math.sin(s["phase"] + self.t * 1.3) > 0.55:
                canvas.put(s["x"], s["y"], ".", self._colors[0])


class Clouds:

    TEMPLATES = [
        [
            " .--. ",
            "(    )",
            " `--' ",
        ],
        [
            "   .---.   ",
            " .(     ). ",
            "(         )",
            " `-------' ",
        ],
        [
            "   .--.  .--.   ",
            " .'    ''.   '. ",
            "(              )",
            " '--.    .--.  '",
            "     '--'  '--' ",
        ],
        [
            "        .--.        .--.",
            "   .---'    '---.--'    '---.",
            "  (                         )",
            "   '---.   .---.   .---.   .'",
            "        '--'   '---'   '--'",
        ],
        [
            "          .---.         .---.",
            "     .---'     '---.--'      '.",
            "   .'                          '.",
            "  (                              )",
            "   '---.     .---.     .---.   .'",
            "        '---'     '---'     '--'",
        ],
    ]

    def __init__(self, w, h, pal, rng=None):
        self.rng = rng or random.Random()
        self.pal = pal
        self.t = 0.0
        self.set_palette(pal)
        self.resize(w, h)

    def set_palette(self, pal):
        self.pal = pal
        bg = pal["bg"]
        self._colors = [
            fade(pal["fg"], bg, 0.82),
            fade(pal["fg"], bg, 0.68),
            fade(pal["fg"], bg, 0.55),
            mix(pal["fg"], pal["primary"], 0.5),
            mix(pal["fg"], pal["primary"], 0.32),
        ]
        self._bird_colors = [
            fade(pal["fg"], bg, 0.55),
            fade(pal["fg"], bg, 0.38),
            mix(pal["fg"], pal["secondary"], 0.25),
        ]

    def resize(self, w, h):
        self.w, self.h = w, h
        count = max(5, min(14, int(w * h / 1200) + 4))
        self.clouds = [self._cloud(anywhere=True) for _ in range(count)]

        if w >= 60:
            big = self._cloud(depth=self.rng.choice([3, 4]))
            width = max(len(row) for row in big["rows"])
            big["x"] = self.rng.uniform(0, max(0.0, w - width))
            self.clouds[0] = big

        self.rng.shuffle(self.clouds)
        for index, cloud in enumerate(self.clouds):
            band = (index + self.rng.random()) / len(self.clouds)
            cloud["y"] = band * max(1.0, h - 5)

        self.birds = [self._bird() for _ in range(max(3, int(w / 40)))]

    def _cloud(self, anywhere=False, depth=None):
        weights = [6, 5, 4, 2, 1]
        possible = [
            index
            for index, rows in enumerate(self.TEMPLATES)
            if max(len(row) for row in rows) <= self.w
        ] or [0]
        if depth is None:
            depth = self.rng.choices(
                possible, weights=[weights[index] for index in possible]
            )[0]
        elif depth not in possible:
            depth = possible[-1]

        rows = self.TEMPLATES[depth]
        width = max(len(row) for row in rows)
        if anywhere:
            x = self.rng.uniform(-width, self.w)
        else:
            x = -width - self.rng.uniform(0, max(4, self.w * 0.3))
        return {
            "x": x,
            "y": self.rng.uniform(0, max(1.0, self.h - 4)),
            "speed": [0.55, 0.85, 1.2, 1.8, 2.5][depth]
            * self.rng.uniform(0.85, 1.2),
            "phase": self.rng.uniform(0, math.tau),
            "depth": depth,
            "rows": rows,
        }

    def _bird(self, direction=None):
        depth = self.rng.choices([0, 1, 2], weights=[3, 3, 2])[0]
        return {
            "x": self.rng.uniform(0, max(1.0, self.w - 3)),
            "y": self.rng.uniform(1, max(1.0, self.h * 0.38)),
            "speed": [2.8, 4.4, 6.2][depth] * self.rng.uniform(0.85, 1.15),
            "dir": direction if direction is not None else self.rng.choice([-1, 1]),
            "phase": self.rng.uniform(0, math.tau),
            "flap": self.rng.uniform(7, 10),
            "depth": depth,
        }

    def step(self, dt):
        self.t += dt
        for c in self.clouds:
            c["x"] += c["speed"] * dt
            if c["x"] > self.w + 2:
                c.update(self._cloud())

        for bird in self.birds:
            bird["x"] += bird["speed"] * bird["dir"] * dt
            if bird["x"] > self.w + 5:
                bird.update(self._bird(direction=1))
                bird["x"] = -3.0
            elif bird["x"] < -5:
                bird.update(self._bird(direction=-1))
                bird["x"] = self.w + 2.0

    def _draw_birds(self, canvas):
        for bird in self.birds:
            flap = math.sin(bird["phase"] + self.t * bird["flap"])
            if bird["depth"] == 0:
                ch = "^" if flap > 0 else "v"
            else:
                ch = "\\^/" if flap > 0 else "/v\\"

            color = self._bird_colors[bird["depth"]]
            x = int(round(bird["x"]))
            y = int(round(bird["y"] + 0.4 * math.sin(self.t * 0.8 + bird["phase"])))
            if bird["depth"] == 0:
                canvas.put(x, y, ch, color)
            else:
                for offset, part in enumerate(ch):
                    canvas.put(x + offset - 1, y, part, color)

    def draw(self, canvas):
        for c in sorted(self.clouds, key=lambda cloud: cloud["depth"]):
            color = self._colors[c["depth"]]
            x = int(round(c["x"]))
            y = int(round(c["y"] + 0.5 * math.sin(c["phase"] + self.t * 0.25)))
            for dy, row in enumerate(c["rows"]):
                for dx, ch in enumerate(row):
                    if ch != " ":
                        canvas.put(x + dx, y + dy, ch, color)

        self._draw_birds(canvas)


class Lilies:

    BASE_RED = "#e0283c"
    BASE_DEEP = "#a8142a"
    BASE_STEM = "#5c8a56"
    ARMS = (
        (-55, 0, 55),
        (-72, -38, 0, 38, 72),
        (-82, -58, -32, 0, 32, 58, 82),
    )
    REACH = (3, 5, 8)
    HEIGHT = ((0.14, 0.22), (0.24, 0.34), (0.36, 0.48))
    SPACING = (7, 11, 17)
    SWAY = (1.6, 2.4, 3.2)
    PIECES = ["'", ",", "`", "."]

    def __init__(self, w, h, pal, rng=None):
        self.rng = rng or random.Random()
        self.pal = pal
        self.t = 0.0
        self.gust = 0.0
        self.set_palette(pal)
        self.resize(w, h)

    def set_palette(self, pal):
        self.pal = pal
        bg = pal["bg"]
        fg = pal["fg"]
        light_theme = Color.parse(bg).brightness > 0.55

        red = mix(self.BASE_RED, pal["accent"], 0.1)
        deep = mix(self.BASE_DEEP, pal["accent"], 0.08)
        stem = mix(self.BASE_STEM, pal["secondary"], 0.15)
        if light_theme:
            red = fade(red, fg, 0.15)
            deep = fade(deep, fg, 0.2)
            stem = fade(stem, fg, 0.25)
            soul = pal["primary"]
        else:
            soul = mix(pal["secondary"], fg, 0.45)

        self._depth = []
        for amount in (0.58, 0.3, 0.0):
            self._depth.append(
                {
                    "red": fade(red, bg, amount),
                    "deep": fade(deep, bg, amount),
                    "tip": fade(mix(red, fg, 0.45), bg, amount),
                    "stem": fade(stem, bg, amount),
                    "wilt": fade(deep, bg, min(0.9, amount + 0.45)),
                }
            )
        self._souls = [fade(soul, bg, 0.65), fade(soul, bg, 0.35), soul]
        self._grass = fade(stem, bg, 0.55)
        self._cloud_colors = [
            mix(fade(fg, bg, amount), red, 0.12)
            for amount in (0.84, 0.76, 0.68, 0.6, 0.52)
        ]

    def resize(self, w, h):
        self.w, self.h = w, h
        self.ground = h - 1
        self.lilies = []
        for depth in range(3):
            spacing = self.SPACING[depth]
            x = self.rng.uniform(0, spacing)
            while x < w:
                self.lilies.append(self._lily(depth, x))
                x += spacing * self.rng.uniform(0.6, 1.4)

        self.grass = [
            {
                "x": x,
                "ch": self.rng.choice(["'", ",", "|"]),
                "phase": self.rng.uniform(0, math.tau),
            }
            for x in range(w)
            if self.rng.random() < 0.3
        ]
        self.pieces = []
        self.landed = []
        self.souls = []
        self.spawn = 0.0
        self.soul_rate = max(3.0, w * h * 0.0006)
        count = max(2, min(6, w // 30))
        clouds = [self._cloud(anywhere=True) for _ in range(count)]
        self.clouds = [c for c in clouds if c is not None]

    def _cloud(self, anywhere=False):
        top = max(3, int(self.h * 0.3))
        fit = [
            i
            for i, rows in enumerate(Clouds.TEMPLATES)
            if max(len(row) for row in rows) <= self.w and len(rows) <= top
        ]
        if not fit:
            return None
        weights = [6, 5, 4, 2, 1]
        index = self.rng.choices(fit, weights=[weights[i] for i in fit])[0]
        rows = Clouds.TEMPLATES[index]
        width = max(len(row) for row in rows)
        if anywhere:
            x = self.rng.uniform(-width, self.w)
        else:
            x = -width - self.rng.uniform(0, max(4, self.w * 0.3))
        return {
            "x": x,
            "y": self.rng.uniform(0, max(0.0, top - len(rows))),
            "speed": [0.55, 0.85, 1.2, 1.8, 2.5][index] * self.rng.uniform(0.85, 1.2),
            "phase": self.rng.uniform(0, math.tau),
            "index": index,
            "rows": rows,
            "width": width,
        }

    def _lily(self, depth, x):
        low, high = self.HEIGHT[depth]
        height = max(3, min(self.h - 2, int(self.h * self.rng.uniform(low, high))))
        arms = []
        for angle in self.ARMS[depth]:
            a = math.radians(angle + self.rng.uniform(-7, 7))
            arms.append((math.sin(a), math.cos(a), self.rng.uniform(0.75, 1.0)))
        lily = {
            "x": x,
            "depth": depth,
            "height": height,
            "arms": arms,
            "phase": self.rng.uniform(0, math.tau),
        }
        self._roll(lily, anywhere=True)
        return lily

    def _roll(self, lily, anywhere=False):
        rng = self.rng
        lily["g"] = rng.uniform(3, 6)
        lily["b"] = rng.uniform(2.5, 4)
        lily["h"] = rng.uniform(9, 20)
        lily["w"] = rng.uniform(3, 5)
        lily["f"] = rng.uniform(1.5, 2.5)
        lily["r"] = rng.uniform(1.5, 6)
        total = sum(lily[k] for k in "gbhwfr")
        lily["total"] = total
        if anywhere:
            lily["t"] = rng.uniform(0, total)
        else:
            lily["t"] = 0.0
            lily["x"] = max(0.0, min(self.w - 1.0, lily["x"] + rng.uniform(-3, 3)))

    @staticmethod
    def _ease(p):
        return p * p * (3 - 2 * p)

    def _state(self, lily):
        t = lily["t"]
        if t < lily["g"]:
            return self._ease(t / lily["g"]), 0.0, 0.0
        t -= lily["g"]
        if t < lily["b"]:
            return 1.0, self._ease(t / lily["b"]), 0.0
        t -= lily["b"]
        if t < lily["h"]:
            return 1.0, 1.0, 0.0
        t -= lily["h"]
        if t < lily["w"]:
            p = t / lily["w"]
            return 1.0, 1.0 - p, p
        t -= lily["w"]
        if t < lily["f"]:
            return 1.0 - t / lily["f"], 0.0, 1.0
        return 0.0, 0.0, 1.0

    def wind(self):
        return max(
            -1.0,
            min(
                1.0,
                0.55 * math.sin(self.t * 0.6)
                + 0.3 * math.sin(self.t * 1.7 + 1.0)
                + self.gust,
            ),
        )

    def _offset(self, lily, rel, wind):
        flutter = 0.35 * math.sin(self.t * 1.4 + lily["phase"])
        return (wind * self.SWAY[lily["depth"]] + flutter) * rel ** 1.4

    def _tip(self, lily, wind):
        return lily["x"] + self._offset(lily, 1.0, wind), self.ground - lily["height"]

    def step(self, dt):
        self.t += dt
        self.gust *= math.exp(-dt * 0.8)
        if self.rng.random() < 0.1 * dt:
            self.gust = self.rng.uniform(-0.8, 0.8)
        wind = self.wind()
        rng = self.rng

        for c in self.clouds:
            c["x"] += c["speed"] * dt
            if c["x"] > self.w + 2:
                fresh = self._cloud()
                if fresh is not None:
                    c.update(fresh)

        for lily in self.lilies:
            lily["t"] += dt
            if lily["t"] >= lily["total"]:
                self._roll(lily)
                continue
            _, openness, wilt = self._state(lily)
            if (
                wilt > 0
                and openness > 0.05
                and len(self.pieces) < 140
                and rng.random() < dt * 5
            ):
                x, y = self._tip(lily, wind)
                self.pieces.append(
                    {
                        "x": x + rng.uniform(-2, 2),
                        "y": y + rng.uniform(0, 1.5),
                        "vy": rng.uniform(2, 4),
                        "phase": rng.uniform(0, math.tau),
                        "depth": lily["depth"],
                        "ch": rng.choice(self.PIECES),
                    }
                )

        for p in self.pieces:
            p["y"] += p["vy"] * dt
            p["x"] += (wind * 3 + math.sin(p["phase"] + self.t * 2) * 1.2) * dt
            if p["y"] >= self.ground and len(self.landed) < 100:
                self.landed.append({"x": p["x"], "depth": p["depth"], "age": 0.0})
        self.pieces = [p for p in self.pieces if p["y"] < self.ground]
        for p in self.landed:
            p["age"] += dt
        self.landed = [p for p in self.landed if p["age"] < 5.0]

        self.spawn += dt * self.soul_rate
        if self.spawn >= 1:
            openers = [l for l in self.lilies if self._state(l)[1] > 0.6]
            while self.spawn >= 1:
                self.spawn -= 1
                if len(self.souls) >= 160:
                    continue
                if openers and rng.random() < 0.85:
                    x, y = self._tip(rng.choice(openers), wind)
                    y -= 1
                else:
                    x = rng.uniform(0, self.w)
                    y = self.ground - rng.uniform(0, self.h * 0.3)
                self.souls.append(
                    {
                        "x0": x,
                        "y": y,
                        "vy": rng.uniform(1.5, 3.0),
                        "phase": rng.uniform(0, math.tau),
                        "freq": rng.uniform(0.6, 1.6),
                        "amp": rng.uniform(0.6, 1.6),
                        "age": 0.0,
                        "life": rng.uniform(5, 9),
                    }
                )
        self.spawn = min(self.spawn, 3)

        for s in self.souls:
            s["y"] -= s["vy"] * dt
            s["x0"] += wind * 1.5 * dt
            s["age"] += dt
        self.souls = [s for s in self.souls if s["age"] < s["life"] and s["y"] > -2]

    def _tone(self, shade, key, wilt):
        color = shade[key]
        if wilt <= 0:
            return color
        return mix(color, shade["wilt"], round(wilt * 3) / 3)

    def _draw_lily(self, canvas, lily, wind):
        stem, openness, wilt = self._state(lily)
        height = int(round(lily["height"] * stem))
        if height < 1:
            return
        shade = self._depth[lily["depth"]]
        ground = self.ground

        xs = [
            int(round(lily["x"] + self._offset(lily, k / lily["height"], wind)))
            for k in range(height + 1)
        ]
        for k in range(height):
            dx = xs[k + 1] - xs[k]
            ch = "/" if dx > 0 else "\\" if dx < 0 else "|"
            canvas.put(xs[k], ground - k, ch, shade["stem"])

        top_x, top_y = xs[height], ground - height
        if openness <= 0.05:
            if wilt == 0:
                if stem < 0.85:
                    canvas.put(top_x, top_y, "'", shade["stem"])
                else:
                    canvas.put(top_x, top_y, "^", shade["deep"])
            return

        reach = self.REACH[lily["depth"]]
        main = self._tone(shade, "red", wilt)
        deep = self._tone(shade, "deep", wilt)
        tip = self._tone(shade, "tip", wilt)
        count = max(1, int(round(reach * openness)))
        sparkle = "*" if int(self.t * 2 + lily["phase"]) % 5 else "+"

        canvas.put(top_x, top_y, "Y", deep)
        for sx, cy, scale in lily["arms"]:
            n = max(1, int(round(count * scale)))
            for j in range(1, n + 1):
                t = j / reach
                px = top_x + sx * j * 1.7
                py = top_y - cy * j * 0.85 + abs(sx) * t * t * reach * 0.35
                if j == n:
                    canvas.put(px, py, sparkle if openness > 0.5 else "'", tip)
                    continue
                if abs(sx) < 0.25:
                    ch = "|"
                elif t > 0.6 and abs(sx) > 0.5:
                    ch = "\\" if sx > 0 else "/"
                elif sx > 0:
                    ch = "/"
                else:
                    ch = "\\"
                canvas.put(px, py, ch, deep if j == 1 else main)

    def draw(self, canvas):
        wind = self.wind()

        for c in sorted(self.clouds, key=lambda cloud: cloud["index"]):
            color = self._cloud_colors[c["index"]]
            x = int(round(c["x"]))
            y = int(round(c["y"] + 0.5 * math.sin(c["phase"] + self.t * 0.25)))
            for dy, row in enumerate(c["rows"]):
                for dx, ch in enumerate(row):
                    if ch != " ":
                        canvas.put(x + dx, y + dy, ch, color)

        for g in self.grass:
            x = g["x"] + 0.6 * math.sin(self.t * 1.1 + g["phase"]) + wind * 0.8
            canvas.put(x, self.ground, g["ch"], self._grass)

        for lily in self.lilies:
            self._draw_lily(canvas, lily, wind)

        bg = self.pal["bg"]
        for p in self.landed:
            shade = self._depth[p["depth"]]
            color = shade["red"] if p["age"] < 3.0 else fade(shade["red"], bg, 0.6)
            canvas.put(p["x"], self.ground, ".", color)
        for p in self.pieces:
            canvas.put(p["x"], p["y"], p["ch"], self._depth[p["depth"]]["red"])

        colors = self._souls
        for s in self.souls:
            f = s["age"] / s["life"]
            x = s["x0"] + s["amp"] * math.sin(s["phase"] + s["freq"] * self.t)
            if f < 0.12 or f > 0.85:
                canvas.put(x, s["y"], ".", colors[0])
            elif f < 0.3 or f > 0.7:
                canvas.put(x, s["y"], "+", colors[1])
            else:
                canvas.put(x, s["y"], "*", colors[2])
                canvas.put(x, s["y"] + 1, ".", colors[0])


SCENES = {
    "rain": Rain,
    "snow": Snow,
    "stars": Stars,
    "sakura": Sakura,
    "fireflies": Fireflies,
    "waves": Waves,
    "clouds": Clouds,
    "lilies": Lilies,
}


def make_scene(kind, w, h, pal, rng=None):
    scene = SCENES.get(kind)
    return scene(w, h, pal, rng) if scene else None


class AnimationEngine:

    def __init__(self, app):
        self.app = app
        self.kind = "off"
        self.scene = None
        self.canvas = None
        self.pal = None
        self.backdrops = set()
        self._theme = None
        self._timer = None
        self._last = time.monotonic()

    def start(self, kind):
        self._timer = self.app.set_interval(1 / FPS, self.tick)
        self.set_kind(kind)

    def set_kind(self, kind):
        if self._timer is not None and kind == self.kind and (self.scene is not None or kind == "off"):
            return

        self.kind = kind
        self.scene = None
        self.canvas = None
        self._build()
        if self._timer is not None:
            if kind == "off":
                self._timer.pause()
            else:
                self._last = time.monotonic()
                self._timer.resume()
        self._refresh(everywhere=True)

    def _palette(self):
        changed = self._theme is not None and self._theme != self.app.theme
        self._theme = self.app.theme
        self.pal = make_palette(self.app.get_css_variables())
        if changed:
            for backdrop in self.backdrops:
                backdrop.clear_styles()
        return self.pal

    def background(self):
        if self.pal is None or self._theme != self.app.theme:
            self._palette()
        return self.pal["bg"]

    def _build(self):
        size = self.app.size
        if self.kind == "off" or size.width < 10 or size.height < 5:
            return
        self.canvas = Canvas(size.width, size.height)
        self.scene = make_scene(self.kind, size.width, size.height, self._palette())

    def tick(self):
        if self.kind == "off":
            return

        size = self.app.size
        if self.scene is None or self.canvas is None or (size.width, size.height) != (self.canvas.w, self.canvas.h):
            self._build()
            if self.scene is None:
                return

        if self._theme != self.app.theme:
            self.scene.set_palette(self._palette())

        now = time.monotonic()
        dt = min(now - self._last, 0.25)
        self._last = now

        self.scene.step(dt)
        self.canvas.clear()
        self.scene.draw(self.canvas)
        self._refresh()

    def _visible_screens(self):
        visible = []
        for screen in reversed(self.app.screen_stack):
            visible.append(screen)
            if not isinstance(screen, ModalScreen):
                break
        return visible

    def _refresh(self, everywhere=False):
        visible = None if everywhere else self._visible_screens()
        for backdrop in list(self.backdrops):
            if backdrop.is_attached and (everywhere or backdrop.screen in visible):
                backdrop.refresh()


class Backdrop(Widget):

    DEFAULT_CSS = """
    Backdrop {
        width: 100%;
        height: 100%;
        background: $background;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._styles = {}

    def on_mount(self):
        self.app.engine.backdrops.add(self)

    def on_unmount(self):
        self.app.engine.backdrops.discard(self)

    def _style(self, color, background):
        key = (color, background)
        if key not in self._styles:
            self._styles[key] = Style(color=color, bgcolor=background)
        return self._styles[key]

    def clear_styles(self):
        self._styles.clear()

    def render_line(self, y: int) -> Strip:
        width = self.size.width
        engine = self.app.engine
        canvas, pal = engine.canvas, engine.pal
        if canvas is None or pal is None or y >= canvas.h:
            return Strip.blank(width, Style(bgcolor=engine.background()))

        background = pal["bg"]
        if canvas.flash > 0:
            background = fade(pal["fg"], pal["bg"], 1 - 0.12 * canvas.flash)

        segments = []
        run = []
        current = None
        for ch, color in zip(canvas.chars[y], canvas.colors[y]):
            if color != current and run:
                segments.append(Segment("".join(run), self._style(current, background)))
                run = []
            current = color
            run.append(ch)
        if run:
            segments.append(Segment("".join(run), self._style(current, background)))

        return Strip(segments, canvas.w).adjust_cell_length(width)
