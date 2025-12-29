import os
from typing import Dict
from fastapi import HTTPException, Header
from jose import jwt
from jose.exceptions import JWTError
from functools import lru_cache
import requests
from dotenv import load_dotenv
from typing import Tuple

load_dotenv()


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

    return get_userinfo(token)


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
