from typing import Any

from fastapi import HTTPException

from app.services.token_store import token_store


async def resolve_user_credentials(token: str) -> dict[str, Any]:
    """Resolve credentials from Redis token."""
    if not token:
        raise HTTPException(
            status_code=400,
            detail="Missing credentials token. Please reinstall the addon.",
        )

    payload = await token_store.get_payload(token)
    if not payload:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token. Please reconfigure the addon.",
        )

    include_watched = payload.get("includeWatched", False)
    username = payload.get("username")
    password = payload.get("password")
    auth_key = payload.get("authKey")

    if not auth_key and (not username or not password):
        raise HTTPException(
            status_code=400,
            detail="Stored token is missing credentials. Please reconfigure the addon.",
        )

    return {
        "username": username,
        "password": password,
        "authKey": auth_key,
        "includeWatched": include_watched,
    }
