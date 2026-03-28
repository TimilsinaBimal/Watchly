from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException
from loguru import logger

from app.core.security import redact_token
from app.core.settings import UserSettings, get_default_settings
from app.models.library import LibraryCollection
from app.services.auth import auth_service
from app.services.stremio.service import StremioBundle
from app.services.token_store import token_store
from app.services.user_cache import user_cache


@dataclass
class UserContext:
    """Everything a request handler needs about a user.

    The caller MUST call close() when done (or use as async context manager).
    """

    token: str
    credentials: dict[str, Any]
    user_settings: UserSettings
    auth_key: str | None
    library: LibraryCollection
    bundle: StremioBundle

    async def close(self):
        await self.bundle.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.close()


def extract_settings(credentials: dict[str, Any]) -> UserSettings:
    """Parse UserSettings from credentials, falling back to defaults."""
    settings_dict = credentials.get("settings", {})
    return UserSettings(**settings_dict) if settings_dict else get_default_settings()


async def load_user_context(
    token: str,
    *,
    require_auth: bool = True,
) -> UserContext:
    """Load credentials, settings, auth key, and library for a token.

    Args:
        token: User token
        require_auth: If True, raises 401 on auth failure. If False, auth_key may be None.

    Returns:
        UserContext with all resolved data. Caller must call .close().
    """
    if not token:
        raise HTTPException(
            status_code=401,
            detail="Missing token. Please reconfigure the addon.",
        )

    credentials = await token_store.get_user_data(token)
    if not credentials:
        raise HTTPException(
            status_code=401,
            detail="Token not found. Please reconfigure the addon.",
        )

    user_settings = extract_settings(credentials)
    bundle = StremioBundle()

    try:
        if require_auth:
            auth_key = await auth_service.require_auth_key(bundle, credentials, token)
        else:
            auth_key = await auth_service.resolve_auth_key_with_bundle(bundle, credentials, token)

        library = await user_cache.get_library_items(token)
        if not library and auth_key:
            logger.info(f"[{redact_token(token)}] Library not cached, fetching from Stremio")
            library = await bundle.library.get_library_items(auth_key)
            await user_cache.set_library_items(token, library)

        if not library:
            library = LibraryCollection()

        return UserContext(
            token=token,
            credentials=credentials,
            user_settings=user_settings,
            auth_key=auth_key,
            library=library,
            bundle=bundle,
        )
    except Exception:
        await bundle.close()
        raise
