import hashlib
import html
import json
import re
import shutil
import time

import requests

from anilixy.core.storage import CACHE_DIR, load_json, write_json

URL = "https://graphql.anilist.co"

API_CACHE_DIR = CACHE_DIR / "anilist"
PUBLIC_TTL = 6 * 3600
USER_TTL = 10 * 60


def _cache_path(query, variables, token):
    scope = "user" if token else "public"
    key = json.dumps([query, variables, bool(token)], sort_keys=True)
    return API_CACHE_DIR / scope / (hashlib.sha1(key.encode("utf-8")).hexdigest() + ".json")


def _query(query, variables, token=None, ttl=None):
    path = _cache_path(query, variables, token) if ttl else None
    if path is not None:
        try:
            if time.time() - path.stat().st_mtime < ttl:
                cached = load_json(path, default=None)
                if cached:
                    return cached
        except OSError:
            pass
    response = requests.post(
        URL,
        json={"query": query, "variables": variables},
        headers={"Authorization": f"Bearer {token}"} if token else {},
        timeout=10,
    )
    response.raise_for_status()
    payload = response.json()
    if path is not None and payload.get("data") and not payload.get("errors"):
        try:
            write_json(path, payload, indent=None, mode=0o600)
        except OSError:
            pass
    return payload


def invalidate_user_cache() -> None:
    shutil.rmtree(API_CACHE_DIR / "user", ignore_errors=True)


def api_cache_stats():
    count = 0
    size = 0
    if API_CACHE_DIR.is_dir():
        for path in API_CACHE_DIR.rglob("*.json"):
            try:
                size += path.stat().st_size
                count += 1
            except OSError:
                pass
    return count, size


def clear_api_cache():
    count, size = api_cache_stats()
    shutil.rmtree(API_CACHE_DIR, ignore_errors=True)
    return count, size

def clean_description(text):
    text = (text or "No synopsis.").replace("<br>", "\n")
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()


FAVOURITE_MUTATION = """
mutation ($animeId: Int, $mangaId: Int, $characterId: Int, $staffId: Int, $studioId: Int) {
  ToggleFavourite(
    animeId: $animeId
    mangaId: $mangaId
    characterId: $characterId
    staffId: $staffId
    studioId: $studioId
  ) {
    anime { nodes { id } }
    manga { nodes { id } }
    characters { nodes { id } }
    staff { nodes { id } }
    studios { nodes { id } }
  }
}
"""


def toggle_favourite(
    token,
    anime_id=None,
    manga_id=None,
    character_id=None,
    staff_id=None,
    studio_id=None,
):
    variables = {}
    if anime_id is not None:
        variables["animeId"] = anime_id
    if manga_id is not None:
        variables["mangaId"] = manga_id
    if character_id is not None:
        variables["characterId"] = character_id
    if staff_id is not None:
        variables["staffId"] = staff_id
    if studio_id is not None:
        variables["studioId"] = studio_id
    invalidate_user_cache()
    response = requests.post(
        URL,
        json={"query": FAVOURITE_MUTATION, "variables": variables},
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    if response.status_code in (400, 401):
        payload = response.json()
        errors = payload.get("errors") or []
        message = (
            " ".join(str(error.get("message") or "") for error in errors)
            or "AniList request failed"
        )
        raise requests.RequestException(message)
    response.raise_for_status()
    payload = response.json()
    if payload.get("errors"):
        message = payload["errors"][0].get("message") or "AniList request failed"
        raise requests.RequestException(message)
    if not payload.get("data") or payload["data"].get("ToggleFavourite") is None:
        raise requests.RequestException("Invalid response")
    return payload["data"]["ToggleFavourite"]


SEARCH_QUERY = """
query ($search: String, $page: Int) {
  Page(page: $page, perPage: 50) {
    pageInfo { hasNextPage }
    media(search: $search, type: ANIME, sort: SEARCH_MATCH) {
      id
      title { romaji english }
      description
      coverImage { extraLarge large }
      averageScore
      episodes
      genres
      siteUrl
      format
      seasonYear
    }
  }
}
"""

MAX_PAGES = 4


def search_anime(name):
    results = []

    for page in range(1, MAX_PAGES + 1):
        response = requests.post(
            URL,
            json={"query": SEARCH_QUERY, "variables": {"search": name, "page": page}},
            timeout=10,
        )
        response.raise_for_status()

        data = response.json()["data"]["Page"]
        results.extend(data["media"])

        if not data["pageInfo"]["hasNextPage"]:
            break

    results.sort(key=lambda a: (a["title"]["english"] or a["title"]["romaji"]).lower())
    return results


CHARACTER_SEARCH_QUERY = """
query ($search: String, $page: Int) {
  Page(page: $page, perPage: 50) {
    pageInfo { hasNextPage }
    characters(search: $search) {
      id
      name { full native }
      image { medium }
    }
  }
}
"""


def search_character(name):
    results = []

    for page in range(1, MAX_PAGES + 1):
        response = requests.post(
            URL,
            json={
                "query": CHARACTER_SEARCH_QUERY,
                "variables": {"search": name, "page": page},
            },
            timeout=10,
        )
        response.raise_for_status()

        data = response.json()["data"]["Page"]
        results.extend(data["characters"])

        if not data["pageInfo"]["hasNextPage"]:
            break

    results.sort(key=lambda c: (c["name"]["full"] or "").lower())
    return results


STAFF_SEARCH_QUERY = """
query ($search: String, $page: Int) {
  Page(page: $page, perPage: 50) {
    pageInfo { hasNextPage }
    staff(search: $search) {
      id
      name { full native }
      image { medium }
    }
  }
}
"""


def search_staff(name):
    results = []

    for page in range(1, MAX_PAGES + 1):
        response = requests.post(
            URL,
            json={
                "query": STAFF_SEARCH_QUERY,
                "variables": {"search": name, "page": page},
            },
            timeout=10,
        )
        response.raise_for_status()

        data = response.json()["data"]["Page"]
        results.extend(data["staff"])

        if not data["pageInfo"]["hasNextPage"]:
            break

    results.sort(key=lambda s: (s["name"]["full"] or "").lower())
    return results


STUDIO_SEARCH_QUERY = """
query ($search: String, $page: Int) {
  Page(page: $page, perPage: 50) {
    pageInfo { hasNextPage }
    studios(search: $search) {
      id
      name
    }
  }
}
"""


def search_studio(name):
    results = []

    for page in range(1, MAX_PAGES + 1):
        response = requests.post(
            URL,
            json={
                "query": STUDIO_SEARCH_QUERY,
                "variables": {"search": name, "page": page},
            },
            timeout=10,
        )
        response.raise_for_status()

        data = response.json()["data"]["Page"]
        results.extend(data["studios"])

        if not data["pageInfo"]["hasNextPage"]:
            break

    results.sort(key=lambda s: (s.get("name") or "").lower())
    return results


DETAILS_QUERY = """
query ($id: Int) {
  Media(id: $id) {
    id
    type
    isFavourite
    duration
    startDate { year month day }
    endDate { year month day }
    season
    seasonYear
    nextAiringEpisode { episode airingAt }
    source
    title { romaji english native }
    synonyms
    studios { nodes { id name isAnimationStudio } }
    staff(sort: RELEVANCE, perPage: 8) {
      edges { role node { id name { full } } }
    }
    characters(sort: [ROLE, RELEVANCE], perPage: 12) {
      edges {
        role
        node { id name { full } }
        voiceActors(language: JAPANESE) { name { full } }
      }
    }
    relations {
      edges {
        relationType
        node {
          id
          type
          format
          title { romaji english }
          coverImage { extraLarge large }
        }
      }
    }
    recommendations(sort: RATING_DESC, perPage: 15) {
      nodes {
        rating
        mediaRecommendation {
          id
          type
          format
          averageScore
          title { romaji english }
          coverImage { extraLarge large }
        }
      }
    }
  }
}
"""


def fetch_details(media_id, token=None):
    payload = _query(
        DETAILS_QUERY, {"id": media_id}, token, ttl=USER_TTL if token else PUBLIC_TTL
    )
    return payload["data"]["Media"]


CHARACTER_QUERY = """
query ($id: Int, $page: Int) {
  Character(id: $id) {
    id
    isFavourite
    name { full native alternative alternativeSpoiler }
    image { large medium }
    description
    age
    gender
    dateOfBirth { year month day }
    bloodType
    favourites
    media(sort: POPULARITY_DESC, page: $page, perPage: 50) {
      pageInfo { hasNextPage }
      edges {
        characterRole
        node {
          id
          type
          format
          title { romaji english }
          coverImage { extraLarge large }
        }
      }
    }
  }
}
"""


def fetch_character(character_id, token=None):
    character = None
    page = 1

    while True:
        payload = _query(
            CHARACTER_QUERY,
            {"id": character_id, "page": page},
            token,
            ttl=USER_TTL if token else PUBLIC_TTL,
        )
        current = payload["data"]["Character"]
        media = current.get("media") or {}

        if character is None:
            character = current
        else:
            character["media"]["edges"].extend(media.get("edges") or [])

        if not (media.get("pageInfo") or {}).get("hasNextPage"):
            return character
        page += 1


STAFF_QUERY = """
query ($id: Int, $page: Int) {
  Staff(id: $id) {
    id
    isFavourite
    name { full native alternative }
    image { large medium }
    description
    age
    gender
    dateOfBirth { year month day }
    bloodType
    favourites
    primaryOccupations
    yearsActive
    homeTown
    staffMedia(sort: POPULARITY_DESC, page: $page, perPage: 50) {
      pageInfo { hasNextPage }
      edges {
        staffRole
        node {
          id
          type
          format
          title { romaji english }
          coverImage { extraLarge large }
        }
      }
    }
  }
}
"""


def fetch_staff(staff_id, token=None):
    staff = None
    page = 1

    while True:
        payload = _query(
            STAFF_QUERY,
            {"id": staff_id, "page": page},
            token,
            ttl=USER_TTL if token else PUBLIC_TTL,
        )
        current = payload["data"]["Staff"]
        staff_media = current.get("staffMedia") or {}

        if staff is None:
            staff = current
            staff["media"] = staff.pop("staffMedia")
        else:
            staff["media"]["edges"].extend(staff_media.get("edges") or [])

        if not (staff_media.get("pageInfo") or {}).get("hasNextPage"):
            return staff
        page += 1


MEDIA_QUERY = """
query ($id: Int) {
  Media(id: $id) {
    id
    type
    title { romaji english }
    description
    coverImage { extraLarge large }
    averageScore
    episodes
    chapters
    volumes
    genres
    siteUrl
    format
    seasonYear
    status
    isFavourite
  }
}
"""


def fetch_media(media_id):
    return _query(MEDIA_QUERY, {"id": media_id}, ttl=PUBLIC_TTL)["data"]["Media"]


MANGA_SEARCH_QUERY = """
query ($search: String, $page: Int) {
  Page(page: $page, perPage: 50) {
    pageInfo { hasNextPage }
    media(search: $search, type: MANGA, sort: SEARCH_MATCH) {
      id
      title { romaji english }
      description
      coverImage { extraLarge large }
      averageScore
      chapters
      volumes
      genres
      siteUrl
      format
      seasonYear
      type
    }
  }
}
"""


def search_manga(name):
    results = []

    for page in range(1, MAX_PAGES + 1):
        response = requests.post(
            URL,
            json={
                "query": MANGA_SEARCH_QUERY,
                "variables": {"search": name, "page": page},
            },
            timeout=10,
        )
        response.raise_for_status()

        data = response.json()["data"]["Page"]
        results.extend(data["media"])

        if not data["pageInfo"]["hasNextPage"]:
            break

    results.sort(key=lambda a: (a["title"]["english"] or a["title"]["romaji"]).lower())
    return results


STUDIO_QUERY = """
query ($id: Int, $page: Int) {
  Studio(id: $id) {
    name
    isFavourite
    media(sort: START_DATE_DESC, page: $page, perPage: 50) {
      pageInfo { hasNextPage }
      nodes {
        id
        title { romaji english }
        coverImage { large }
        format
        episodes
        averageScore
        startDate { year }
      }
    }
  }
}
"""


def fetch_studio_page(studio_id, page, token=None):
    payload = _query(
        STUDIO_QUERY,
        {"id": studio_id, "page": page},
        token,
        ttl=USER_TTL if token else PUBLIC_TTL,
    )
    studio = payload["data"]["Studio"]
    media = studio["media"]
    return {
        "animes": media["nodes"],
        "has_next": media["pageInfo"]["hasNextPage"],
        "is_favourite": bool(studio.get("isFavourite")),
    }


PROGRESS_QUERY = """
query ($id: Int) {
  Media(id: $id) {
    episodes
    chapters
    volumes
    mediaListEntry { progress progressVolumes status score(format: POINT_10_DECIMAL) repeat }
  }
}
"""


def fetch_progress(token, media_id):
    response = requests.post(
        URL,
        json={"query": PROGRESS_QUERY, "variables": {"id": media_id}},
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    response.raise_for_status()

    media = response.json()["data"]["Media"]
    entry = media["mediaListEntry"] or {}
    return {
        "progress": entry.get("progress") or 0,
        "progressVolumes": entry.get("progressVolumes") or 0,
        "status": entry.get("status"),
        "score": entry.get("score"),
        "repeat": entry.get("repeat") or 0,
        "episodes": media.get("episodes"),
        "chapters": media.get("chapters"),
        "volumes": media.get("volumes"),
    }


PROGRESS_MUTATION = """
mutation ($mediaId: Int, $progress: Int, $progressVolumes: Int, $status: MediaListStatus, $repeat: Int) {
  SaveMediaListEntry(mediaId: $mediaId, progress: $progress, progressVolumes: $progressVolumes, status: $status, repeat: $repeat) {
    id
    progress
    progressVolumes
    status
    repeat
  }
}
"""


ACTIVE_STATUSES = ("CURRENT", "REPEATING")
RESTART_STATUSES = ("PLANNING", "DROPPED", "PAUSED", "COMPLETED")


def _post_mutation(token, query, variables):
    invalidate_user_cache()
    response = requests.post(
        URL,
        json={"query": query, "variables": variables},
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("errors"):
        message = payload["errors"][0].get("message") or "AniList request failed"
        raise requests.RequestException(message)
    return payload["data"]["SaveMediaListEntry"]


SAVE_ENTRY_MUTATION = """
mutation ($mediaId: Int, $status: MediaListStatus, $progress: Int, $progressVolumes: Int, $scoreRaw: Int, $repeat: Int) {
  SaveMediaListEntry(mediaId: $mediaId, status: $status, progress: $progress, progressVolumes: $progressVolumes, scoreRaw: $scoreRaw, repeat: $repeat) {
    id
    status
    progress
    progressVolumes
    repeat
  }
}
"""


def save_list_entry(
    token,
    media_id,
    status,
    progress=None,
    progress_volumes=None,
    score=None,
    repeat=None,
):
    variables = {"mediaId": media_id, "status": status}
    if progress is not None:
        variables["progress"] = progress
    if progress_volumes is not None:
        variables["progressVolumes"] = progress_volumes
    if score is not None:
        variables["scoreRaw"] = int(round(score * 10))
    if repeat is not None:
        variables["repeat"] = repeat
    return _post_mutation(token, SAVE_ENTRY_MUTATION, variables)


def start_media(token, media_id):
    current = fetch_progress(token, media_id)
    status = current.get("status")
    if status in ACTIVE_STATUSES:
        return None

    new_status = "REPEATING" if status == "COMPLETED" else "CURRENT"
    variables = {"mediaId": media_id, "progress": 0, "status": new_status}
    if current.get("progressVolumes"):
        variables["progressVolumes"] = 0
    _post_mutation(token, PROGRESS_MUTATION, variables)
    return new_status


def save_progress(token, media_id, episode, total_episodes=None):
    current = fetch_progress(token, media_id)
    if episode <= current["progress"]:
        return None

    rewatching = current.get("status") == "REPEATING"
    variables = {"mediaId": media_id, "progress": episode}
    if total_episodes and episode >= total_episodes:
        variables["status"] = "COMPLETED"
        if rewatching:
            variables["repeat"] = current["repeat"] + 1
    else:
        variables["status"] = "REPEATING" if rewatching else "CURRENT"

    return _post_mutation(token, PROGRESS_MUTATION, variables)


WATCHING_ENTRY = """
      entries {
        status
        updatedAt
        progress
        media {
          id
          title { romaji english }
          episodes
          nextAiringEpisode { episode }
        }
      }
"""

WATCHING_QUERY = (
    """
query ($userId: Int) {
  current: MediaListCollection(userId: $userId, type: ANIME, status: CURRENT, sort: UPDATED_TIME_DESC) {
    lists {"""
    + WATCHING_ENTRY
    + """    }
  }
  repeating: MediaListCollection(userId: $userId, type: ANIME, status: REPEATING, sort: UPDATED_TIME_DESC) {
    lists {"""
    + WATCHING_ENTRY
    + """    }
  }
}
"""
)


def _merge_collections(data, keys):
    entries = []
    for key in keys:
        collection = (data or {}).get(key) or {}
        for group in collection.get("lists") or []:
            entries.extend(group["entries"])
    entries.sort(key=lambda entry: entry.get("updatedAt") or 0, reverse=True)
    return entries


def fetch_watching(token, user_id):
    response = requests.post(
        URL,
        json={"query": WATCHING_QUERY, "variables": {"userId": user_id}},
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    response.raise_for_status()
    return _merge_collections(response.json().get("data"), ("current", "repeating"))


def fetch_all_anime_list(token, user_id):
    response = requests.post(
        URL,
        json={"query": ALL_ANIME_QUERY, "variables": {"userId": user_id}},
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    response.raise_for_status()

    entries = []
    for group in response.json()["data"]["MediaListCollection"]["lists"]:
        entries.extend(group["entries"])
    return entries


def fetch_all_manga_list(token, user_id):
    response = requests.post(
        URL,
        json={"query": ALL_MANGA_QUERY, "variables": {"userId": user_id}},
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    response.raise_for_status()

    entries = []
    for group in response.json()["data"]["MediaListCollection"]["lists"]:
        entries.extend(group["entries"])
    return entries


ALL_ANIME_QUERY = """
query ($userId: Int) {
  MediaListCollection(userId: $userId, type: ANIME) {
    lists {
      status
      entries {
        status
        progress
        score
        repeat
        media {
          id
          title { romaji english }
          coverImage { medium large }
          episodes
          format
          averageScore
        }
      }
    }
  }
}
"""


ALL_MANGA_QUERY = """
query ($userId: Int) {
  MediaListCollection(userId: $userId, type: MANGA) {
    lists {
      status
      entries {
        status
        progress
        progressVolumes
        score
        repeat
        media {
          id
          title { romaji english }
          coverImage { medium large }
          chapters
          volumes
          format
          averageScore
        }
      }
    }
  }
}
"""


OVERVIEW_QUERY = """
query ($userId: Int) {
  Viewer {
    id
    name
    avatar { large medium }
    statistics {
      anime {
        count
        episodesWatched
        genres(limit: 10, sort: COUNT_DESC) { genre count }
      }
      manga {
        count
        chaptersRead
        genres(limit: 10, sort: COUNT_DESC) { genre count }
      }
    }
  }
  Page(page: 1, perPage: 15) {
    activities(userId: $userId, type: MEDIA_LIST, sort: ID_DESC) {
      ... on ListActivity {
        id
        status
        progress
        createdAt
        media {
          id
          type
          format
          title { romaji english }
          coverImage { large }
          episodes
          chapters
        }
      }
    }
  }
}
"""


def fetch_overview(token, user_id):
    response = requests.post(
        URL,
        json={"query": OVERVIEW_QUERY, "variables": {"userId": user_id}},
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )

    body = response.json()

    if response.status_code in (400, 401):
        errors = body.get("errors") or []
        message = " ".join(str(error.get("message") or "") for error in errors)
        if response.status_code == 401 or "Invalid token" in message:
            return None

    response.raise_for_status()

    data = body.get("data") or {}
    profile = data.get("Viewer")
    if profile is None:
        return None

    activities = (data.get("Page") or {}).get("activities") or []
    return {"profile": profile, "activities": activities}


READING_ENTRY = """
      entries {
        status
        updatedAt
        progress
        progressVolumes
        media {
          id
          title { romaji english }
          chapters
          volumes
          format
        }
      }
"""

READING_QUERY = (
    """
query ($userId: Int) {
  current: MediaListCollection(userId: $userId, type: MANGA, status: CURRENT, sort: UPDATED_TIME_DESC) {
    lists {"""
    + READING_ENTRY
    + """    }
  }
  repeating: MediaListCollection(userId: $userId, type: MANGA, status: REPEATING, sort: UPDATED_TIME_DESC) {
    lists {"""
    + READING_ENTRY
    + """    }
  }
}
"""
)


def fetch_reading(token, user_id):
    response = requests.post(
        URL,
        json={"query": READING_QUERY, "variables": {"userId": user_id}},
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    response.raise_for_status()
    return _merge_collections(response.json().get("data"), ("current", "repeating"))


FAVORITES_QUERY = """
query ($userId: Int) {
  User(id: $userId) {
    favourites {
      anime { nodes { id type title { romaji english } coverImage { large } format } }
      manga { nodes { id type title { romaji english } coverImage { large } format } }
      characters { nodes { id name { full } image { large } } }
      staff { nodes { id name { full } image { large } } }
      studios { nodes { id name } }
    }
  }
}
"""


def fetch_favorites(token, user_id):
    response = requests.post(
        URL,
        json={"query": FAVORITES_QUERY, "variables": {"userId": user_id}},
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    response.raise_for_status()
    return response.json()["data"]["User"]["favourites"]

NOVEL_PROGRESS_MUTATION = """
mutation ($mediaId: Int, $progress: Int, $status: MediaListStatus, $repeat: Int) {
  SaveMediaListEntry(mediaId: $mediaId, progress: $progress, status: $status, repeat: $repeat) {
    id
    progress
    status
    repeat
  }
}
"""

def save_manga_progress(token, media_id, chapter=None, volume=None):
    current = fetch_progress(token, media_id)
    current_ch = current.get("progress") or 0
    current_vol = current.get("progressVolumes") or 0
    current_status = current.get("status")

    new_ch = max(chapter, current_ch) if chapter is not None else current_ch
    new_vol = max(volume, current_vol) if volume is not None else current_vol

    if (
        new_ch == current_ch
        and new_vol == current_vol
        and current_status in ("CURRENT", "COMPLETED", "REPEATING")
    ):
        return None

    rereading = current_status == "REPEATING"
    total_chapters = current.get("chapters")
    status = "REPEATING" if rereading else "CURRENT"
    repeat = None
    if total_chapters and new_ch >= total_chapters:
        status = "COMPLETED"
        if rereading:
            repeat = current["repeat"] + 1

    if new_vol == 0:
        mutation = NOVEL_PROGRESS_MUTATION
        variables = {"mediaId": media_id, "progress": new_ch, "status": status}
    else:
        mutation = PROGRESS_MUTATION
        variables = {"mediaId": media_id, "progress": new_ch, "progressVolumes": new_vol, "status": status}
    if repeat is not None:
        variables["repeat"] = repeat

    return _post_mutation(token, mutation, variables)
