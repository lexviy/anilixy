from anilixy.core.storage import CONFIG_DIR, load_json, write_json

TOKEN_FILE = CONFIG_DIR / "token.json"
CLIENT_ID_FILE = CONFIG_DIR / "client_id.json"


def load_client_id() -> str | None:
    return load_json(CLIENT_ID_FILE).get("client_id")


def save_client_id(client_id: str) -> None:
    write_json(CLIENT_ID_FILE, {"client_id": client_id}, mode=0o600)


def get_auth_url(client_id) -> str:
    return f"https://anilist.co/api/v2/oauth/authorize?client_id={client_id}&response_type=token"


def save_token(token: str) -> None:
    write_json(TOKEN_FILE, {"access_token": token}, mode=0o600)


def load_token() -> str | None:
    return load_json(TOKEN_FILE).get("access_token")

def logout() -> None:
    if TOKEN_FILE.exists():
        TOKEN_FILE.unlink()
