import time
from pathlib import Path

import jwt
import requests
from app.config import GITHUB_APP_ID, GITHUB_PRIVATE_KEY_PATH


def create_app_jwt() -> str:
    private_key = Path(GITHUB_PRIVATE_KEY_PATH).read_text()

    payload = {
        "iat": int(time.time()) - 60,
        "exp": int(time.time()) + 600,
        "iss": GITHUB_APP_ID,
    }

    return jwt.encode(payload, private_key, algorithm="RS256")


def get_installation_token(installation_id: int) -> str:
    jwt_token = create_app_jwt()

    headers = {
        "Authorization": f"Bearer {jwt_token}",
        "Accept": "application/vnd.github+json",
    }

    url = f"https://api.github.com/app/installations/{installation_id}/access_tokens"

    response = requests.post(url, headers=headers)
    response.raise_for_status()

    return response.json()["token"]
