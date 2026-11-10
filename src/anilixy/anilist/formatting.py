import time

from rich.text import Text

MONTHS = [
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
]

RELATION_ORDER = [
    "PREQUEL",
    "SEQUEL",
    "PARENT",
    "SIDE_STORY",
    "SPIN_OFF",
    "ALTERNATIVE",
    "SUMMARY",
    "SOURCE",
    "ADAPTATION",
]


def nice(value):
    if not value:
        return "?"
    return value.replace("_", " ").capitalize()


def relative_time(timestamp):
    if not timestamp:
        return ""

    seconds = max(0, int(time.time()) - int(timestamp))
    if seconds < 60:
        return "just now"

    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"

    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"

    days = hours // 24
    if days < 30:
        return f"{days}d ago"

    months = days // 30
    if months < 12:
        return f"{months}mo ago"

    return f"{days // 365}y ago"


def format_date(date):
    date = date or {}
    year = date.get("year")
    month = date.get("month")
    day = date.get("day")

    if not year:
        return "?"
    if month and day:
        return f"{MONTHS[month - 1]} {day}, {year}"
    if month:
        return f"{MONTHS[month - 1]} {year}"
    return str(year)


def format_countdown(seconds):
    seconds = max(0, int(seconds))
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60

    parts = []
    if days:
        parts.append(f"{days}d")
    if days or hours:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    return " ".join(parts)


def next_episode_text(d):
    airing = d.get("nextAiringEpisode")
    if not airing or not airing.get("airingAt"):
        return None

    airing_at = airing["airingAt"]
    when = time.strftime("%a, %b %d, %H:%M", time.localtime(airing_at))
    countdown = format_countdown(airing_at - time.time())
    return f"Ep {airing['episode']} in {countdown} ({when})"


def info_text(d, variables=None):
    variables = variables or {}
    primary = variables.get("primary", "cyan")
    secondary = variables.get("secondary", "magenta")
    accent = variables.get("accent", "yellow")
    foreground = variables.get("foreground", "white")

    season = "?"
    if d["season"] and d["seasonYear"]:
        season = f"{d['season'].capitalize()} {d['seasonYear']}"

    rows = [
        ("Duration", f"{d['duration']} min" if d["duration"] else "?"),
        ("Start date", format_date(d["startDate"])),
        ("End date", format_date(d["endDate"])),
        ("Season", season),
        ("Source", nice(d["source"])),
        ("Romaji", d["title"]["romaji"] or "?"),
        ("English", d["title"]["english"] or "?"),
        ("Native", d["title"]["native"] or "?"),
        ("Synonyms", ", ".join(d["synonyms"]) or "?"),
    ]

    next_ep = next_episode_text(d)
    if next_ep:
        rows.insert(0, ("Next ep", next_ep))

    text = Text()
    for label, value in rows:
        if label in ("Romaji", "English", "Native"):
            l_style = f"bold {secondary}"
            v_style = f"bold {accent}"
        elif label == "Next ep":
            l_style = f"bold {primary}"
            v_style = f"bold {accent}"
        elif label == "Synonyms":
            l_style = "italic dim"
            v_style = "italic dim"
        else:
            l_style = f"bold {primary}"
            v_style = foreground

        text.append(f"{label:<12}", style=l_style)
        text.append(f"{value}\n", style=v_style)

    return text


def manga_info_text(d, variables=None):
    variables = variables or {}
    primary = variables.get("primary", "cyan")
    secondary = variables.get("secondary", "magenta")
    accent = variables.get("accent", "yellow")
    foreground = variables.get("foreground", "white")

    rows = [
        ("Start date", format_date(d["startDate"])),
        ("End date", format_date(d["endDate"])),
        ("Source", nice(d["source"])),
        ("Romaji", d["title"]["romaji"] or "?"),
        ("English", d["title"]["english"] or "?"),
        ("Native", d["title"]["native"] or "?"),
        ("Synonyms", ", ".join(d["synonyms"]) or "?"),
    ]

    text = Text()
    for label, value in rows:
        if label in ("Romaji", "English", "Native"):
            l_style = f"bold {secondary}"
            v_style = f"bold {accent}"
        elif label == "Synonyms":
            l_style = "italic dim"
            v_style = "italic dim"
        else:
            l_style = f"bold {primary}"
            v_style = foreground

        text.append(f"{label:<12}", style=l_style)
        text.append(f"{value}\n", style=v_style)

    return text


def split_studios(d):
    nodes = d["studios"]["nodes"]
    studios = [n for n in nodes if n["isAnimationStudio"]]
    producers = [n for n in nodes if not n["isAnimationStudio"]]
    return studios, producers


def relations_list(d):
    items = []

    for edge in d["relations"]["edges"]:
        node = edge["node"]
        title = node["title"]
        relation = edge["relationType"]
        is_anime = node["type"] == "ANIME"

        if relation in RELATION_ORDER:
            order = RELATION_ORDER.index(relation)
        else:
            order = len(RELATION_ORDER)

        kind = nice(relation)
        if not is_anime:
            fmt = "Light novel" if node["format"] == "NOVEL" else nice(node["format"])
            kind = f"{kind}\n{fmt}"

        items.append(
            {
                "id": node["id"],
                "is_anime": is_anime,
                "title": title["english"] or title["romaji"] or "?",
                "kind": kind,
                "order": order,
                "cover_url": (node.get("coverImage") or {}).get("extraLarge")
                or (node.get("coverImage") or {}).get("large"),
                "cover": None,
            }
        )

    items.sort(key=lambda r: r["order"])
    return items


def split_chunk(animes, limit):
    runs = []
    for a in animes:
        year = (a.get("startDate") or {}).get("year")
        if runs and runs[-1][0] == year:
            runs[-1][1].append(a)
        else:
            runs.append((year, [a]))

    chunk = []
    total = 0
    for i, (year, items) in enumerate(runs):
        if chunk and total + len(items) > limit:
            return chunk, runs[i:]
        chunk.append((year, items))
        total += len(items)

    return chunk, []


def anime_details(a):
    details = []
    if a["format"]:
        details.append(a["format"].replace("_", " "))
    if a["episodes"]:
        details.append(f"{a['episodes']} eps")
    if a["averageScore"]:
        details.append(f"{a['averageScore']}%")
    return " · ".join(details)


def recommendations_list(d):
    items = []
    nodes = (d.get("recommendations") or {}).get("nodes") or []

    for node in nodes:
        media = node.get("mediaRecommendation")
        if not media:
            continue

        title = media.get("title") or {}
        if media.get("type") == "ANIME":
            kind = "Anime"
        elif media.get("format") == "NOVEL":
            kind = "Light novel"
        else:
            kind = "Manga"

        score = media.get("averageScore")
        if score:
            kind = f"{kind}\n\u2605 {score}%"

        images = media.get("coverImage") or {}
        items.append(
            {
                "id": media["id"],
                "title": title.get("english") or title.get("romaji") or "?",
                "kind": kind,
                "cover_url": images.get("extraLarge") or images.get("large"),
            }
        )

    return items
