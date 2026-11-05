import requests

from anilixy.anilist.api import URL

VIEWER_QUERY = """
query {
  Viewer {
    id
    name
    avatar { large }
    statistics {
      anime { count episodesWatched }
    }
  }
}
"""


def fetch_profile(token):
    response = requests.post(
        URL,
        json={"query": VIEWER_QUERY},
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )

    if response.status_code in (400, 401):
        return None

    response.raise_for_status()

    data = response.json().get("data") or {}
    return data.get("Viewer")
