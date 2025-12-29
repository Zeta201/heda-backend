from datetime import time
import os
from pathlib import Path
from typing import Dict
from fastapi import HTTPException, Header
from jose import jwt
from jose.exceptions import JWTError
from functools import lru_cache
import requests
from dotenv import load_dotenv
from typing import Tuple

import os
import requests
from fastapi import HTTPException

from app.config import GITHUB_APP_ID, GITHUB_PRIVATE_KEY_PATH

load_dotenv()


GITHUB_ORG = os.environ.get("GITHUB_ORG")  # e.g., "heda-org"
GITHUB_TOKEN = os.environ.get("GITHUB_ADMIN_TOKEN")  # a PAT with org membership read/write access
CLIENT_ID = os.environ.get("CLIENT_ID")  
CLIENT_SECRET = os.environ.get("CLIENT_SECRET")  

# Auth0 configuration
AUTH0_DOMAIN = os.environ.get("AUTH0_DOMAIN")  # e.g., dev-xxxx.us.auth0.com
AUTH0_AUDIENCE = os.environ.get("AUTH0_AUDIENCE")  # e.g., https://heda.example.com/api

JWKS_URL = f"https://{AUTH0_DOMAIN}/.well-known/jwks.json"


@lru_cache()
def get_jwks():
    resp = requests.get(JWKS_URL)
    resp.raise_for_status()
    return resp.json()

def verify_token(token: str) -> dict:
    """
    Verifies the JWT from Auth0 and returns the payload.
    Raises HTTPException(401) if invalid.
    """
    try:
        unverified_header = jwt.get_unverified_header(token)
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid JWT header")

    jwks = get_jwks()
    rsa_key = {}
    for key in jwks["keys"]:
        if key["kid"] == unverified_header.get("kid"):
            rsa_key = {
                "kty": key["kty"],
                "kid": key["kid"],
                "use": key["use"],
                "n": key["n"],
                "e": key["e"]
            }
            break
    if not rsa_key:
        raise HTTPException(status_code=401, detail="Public key not found")

    try:
        payload = jwt.decode(
            token,
            rsa_key,
            algorithms=["RS256"],
            audience=AUTH0_AUDIENCE,
            issuer=f"https://{AUTH0_DOMAIN}/"
        )
    except JWTError:
        raise HTTPException(status_code=401, detail="Token verification failed")

    return payload


def get_current_user(authorization: str = Header(...)) -> Dict:
    """
    Verify Auth0 access token and return full JWT payload.
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid Authorization header")

    token = authorization.removeprefix("Bearer ").strip()
    payload = verify_token(token)

    if not payload.get("sub"):
        raise HTTPException(status_code=401, detail="Invalid token")

    user = get_userinfo(token)
    user.update({
        "user_id": payload.get("sub")
    })
    return user


def extract_user_id(
    user: dict,
    *,
    expected_provider: str | None = "github",
) -> Tuple[str, str]:
    """
    Extract provider and user ID from Auth0 JWT payload.

    Args:
        user: Decoded JWT payload returned by get_current_user
        expected_provider: Restrict to a specific IdP (e.g. "github").
                          Set to None to allow any provider.

    Returns:
        (provider, user_id)

    Raises:
        HTTPException(401/403) if token is invalid or provider not allowed
    """
    sub = user.get("sub")
    if not sub:
        raise HTTPException(status_code=401, detail="Token missing 'sub' claim")

    if "|" not in sub:
        raise HTTPException(status_code=401, detail="Malformed 'sub' claim")

    provider, user_id = sub.split("|", 1)

    if expected_provider and provider != expected_provider:
        raise HTTPException(
            status_code=403,
            detail=f"Unsupported identity provider: {provider}",
        )

    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid user id")

    return provider, user_id

def get_userinfo(token: str) -> Dict:
    r = requests.get(
        f"https://{AUTH0_DOMAIN}/userinfo",
        headers={"Authorization": f"Bearer {token}"},
        timeout=5,
    )
    r.raise_for_status()
    return r.json()


def check_github_org_membership(github_username: str) -> None:
    """
    Ensure that the given GitHub username is a member of the organization.
    Raises HTTPException(403) if not authorized.
    """
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }
    url = f"https://api.github.com/orgs/{GITHUB_ORG}/members/{github_username}"
    resp = requests.get(url, headers=headers, timeout=5)

    if resp.status_code == 404:
        raise HTTPException(
            status_code=403,
            detail=f"User '{github_username}' is not a member of '{GITHUB_ORG}'",
        )
    elif resp.status_code != 204:
        # 204 means user is a member
        raise HTTPException(
            status_code=500,
            detail=f"Failed to verify org membership: {resp.status_code} {resp.text}"
        )


def get_management_api_token() -> str:
    resp = requests.post(
        f"https://{AUTH0_DOMAIN}/oauth/token",
        json={
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "audience": f"https://{AUTH0_DOMAIN}/api/v2/",
            "grant_type": "client_credentials",
        },
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def get_github_token_for_user(user_id: str) -> str:
    mgmt_token = get_management_api_token()

    resp = requests.get(
        f"https://{AUTH0_DOMAIN}/api/v2/users/{user_id}",
        headers={
            "Authorization": f"Bearer {mgmt_token}"
        },
        timeout=10,
    )
    resp.raise_for_status()
    user = resp.json()
    print(f"This is payload {user}")
    for identity in user.get("identities", []):
        if identity.get("provider") == "github":
            github_token = identity.get("access_token")
            if not github_token:
                raise RuntimeError("GitHub token not found in identity")
            return github_token

    raise RuntimeError("No GitHub identity found for user")


def create_app_jwt() -> str:
    private_key = Path(GITHUB_PRIVATE_KEY_PATH).read_text()

    payload = {
        "iat": int(time.time()) - 60,
        "exp": int(time.time()) + 600,
        "iss": GITHUB_APP_ID,
    }

    return jwt.encode(payload, private_key, algorithm="RS256")