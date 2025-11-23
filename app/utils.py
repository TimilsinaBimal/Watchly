from typing import Any

from fastapi import HTTPException

from app.services.token_store import token_store


def redact_token(token: str | None, visible_chars: int = 8) -> str:
    """
    Redact a token for logging purposes.
    Shows first few characters followed by *** for debugging.

    Args:
        token: The token to redact
        visible_chars: Number of characters to show before redaction (default: 8)

    Returns:
        Redacted token string (e.g., "ksfjads***" or "None" if token is None)
    """
    if not token:
        return "None"
    if len(token) <= visible_chars:
        return "***"
    return f"{token[:visible_chars]}***"


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
