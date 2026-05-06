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

    The library is sourced from `user_settings.watch_history_source`:
    Trakt/Simkl history is converted to a LibraryCollection so the
    "Because you watched/loved" catalogs and other library-driven recommenders
    see the user's external history. On any external-fetch failure we fall
    back to the Stremio library so the user still gets recommendations.
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

        configured_source = user_settings.watch_history_source

        # Drop the cached library if it was built from a different source than
        # the one currently configured — otherwise switching sources in the
        # configure page would silently keep serving the old (wrong) library.
        cached = await user_cache.get_library_items(token)
        if cached and getattr(cached, "source", "stremio") != configured_source:
            logger.info(
                f"[{redact_token(token)}] Cached library source "
                f"'{cached.source}' != configured '{configured_source}'; invalidating."
            )
            await user_cache.invalidate_library_items(token)
            cached = None

        library = cached
        if not library:
            library = await _fetch_library_for_source(configured_source, user_settings, token, bundle, auth_key)
            if library is not None:
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


async def _fetch_library_for_source(
    source: str,
    user_settings: UserSettings,
    token: str,
    bundle: StremioBundle,
    auth_key: str | None,
) -> LibraryCollection | None:
    """Fetch the LibraryCollection for the configured watch_history_source.

    Trakt/Simkl: convert WatchHistory to a LibraryCollection. On failure
    (missing token, revoked token, network), fall back to Stremio so the
    user still sees recommendations from whatever Stremio knows about them.
    Stremio: pull directly from the bundle's library service.
    """
    if source in ("trakt", "simkl"):
        from app.services.profile.service import ProfileService

        profile_service = ProfileService()
        external = await profile_service.fetch_external_library(source, user_settings, token)
        if external is not None:
            logger.info(
                f"[{redact_token(token)}] Built library from {source}: "
                f"{len(external.loved)} loved, {len(external.liked)} liked, "
                f"{len(external.watched)} watched"
            )
            return external

        logger.warning(
            f"[{redact_token(token)}] External {source} fetch returned no history; " "falling back to Stremio library."
        )

    if auth_key:
        logger.info(f"[{redact_token(token)}] Fetching library from Stremio")
        return await bundle.library.get_library_items(auth_key)

    return None
