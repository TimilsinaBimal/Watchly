from typing import Any

from fastapi import HTTPException
from loguru import logger

from app.core.config import settings
from app.core.security import redact_token
from app.core.settings import UserSettings, resolve_tmdb_api_key
from app.core.version import __version__
from app.services.catalog import DynamicCatalogService
from app.services.profile.integration import ProfileIntegration
from app.services.stremio.service import StremioBundle
from app.services.token_store import token_store
from app.services.translation import apply_catalog_translation
from app.services.user_cache import user_cache
from app.utils.catalog import cache_profile_and_watched_sets, sort_catalogs


class ManifestService:
    """Service for generating Stremio manifest files."""

    @staticmethod
    def get_base_manifest() -> dict[str, Any]:
        """Get the base manifest structure."""
        return {
            "id": settings.ADDON_ID,
            "version": __version__,
            "name": settings.ADDON_NAME,
            "description": "Movie and series recommendations based on your Stremio library.",
            "logo": ("https://raw.githubusercontent.com/TimilsinaBimal/Watchly/refs/heads/main/app/static/logo.png"),
            "background": (
                "https://raw.githubusercontent.com/TimilsinaBimal/Watchly/refs/heads/main/app/static/cover.png"
            ),
            "resources": ["catalog"],
            "types": ["movie", "series"],
            "idPrefixes": ["tt"],
            "catalogs": [],
            "behaviorHints": {"configurable": True, "configurationRequired": False},
            "stremioAddonsConfig": {
                "issuer": "https://stremio-addons.net",
                "signature": (
                    "eyJhbGciOiJkaXIiLCJlbmMiOiJBMTI4Q0JDLUhTMjU2In0..WSrhzzlj1TuDycD6QoVLuA.Dzmxzr4y83uqQF15r4tC1bB9-vtZRh1Rvy4BqgDYxu91c2esiJuov9KnnI_cboQCgZS7hjwnIqRSlQ-jEyGwXHHRerh9QklyfdxpXqNUyBgTWFzDOVdVvDYJeM_tGMmR.sezAChlWGV7lNS-t9HWB6A"  # noqa
                ),
            },
        }

    async def _resolve_auth_key(self, bundle: StremioBundle, credentials: dict[str, Any], token: str) -> str | None:
        """Resolve and validate auth key, refreshing if needed."""
        auth_key = credentials.get("authKey")
        email = credentials.get("email")
        password = credentials.get("password")

        is_valid = False
        if auth_key:
            try:
                await bundle.auth.get_user_info(auth_key)
                is_valid = True
            except Exception as e:
                logger.debug(f"Auth key check failed for {email or 'unknown'}: {e}")

        if not is_valid and email and password:
            try:
                auth_key = await bundle.auth.login(email, password)
                # Update store
                credentials["authKey"] = auth_key
                await token_store.update_user_data(token, credentials)
            except Exception as e:
                logger.error(f"Failed to refresh auth key during manifest fetch: {e}")
                return None

        return auth_key

    async def cache_library_and_profiles(
        self, bundle: StremioBundle, auth_key: str, user_settings: UserSettings, token: str
    ) -> dict[str, Any]:
        """
        Fetch and cache library items and profiles for a user.

        This should be called during token creation to pre-cache data
        so manifest generation is fast.

        Args:
            bundle: StremioBundle instance
            auth_key: Stremio auth key
            user_settings: User settings
            token: User token

        Returns:
            Library items dictionary
        """
        # Fetch library items
        logger.info(f"[{redact_token(token)}] Fetching library items for caching")
        library_items = await bundle.library.get_library_items(auth_key)

        # Cache library items using centralized cache service
        await user_cache.set_library_items(token, library_items)
        logger.debug(f"[{redact_token(token)}] Cached library items")

        # Build and cache profiles for both movie and series
        language = user_settings.language
        tmdb_key = resolve_tmdb_api_key(user_settings)
        integration_service = ProfileIntegration(language=language, tmdb_api_key=tmdb_key)

        for content_type in ["movie", "series"]:
            try:
                logger.info(f"[{redact_token(token)}] Building and caching profile for {content_type}")
                _, _, _ = await cache_profile_and_watched_sets(
                    token, content_type, integration_service, library_items, bundle, auth_key
                )
                logger.debug(f"[{redact_token(token)}] Cached profile and watched sets for {content_type}")
            except Exception as e:
                logger.warning(f"[{redact_token(token)}] Failed to build/cache profile for {content_type}: {e}")

        return library_items

    async def cache_library_and_profiles_from_items(
        self, library_items: dict, user_settings: UserSettings, token: str
    ) -> None:
        """
        Cache library items and build profiles from an already-fetched library dict.
        Used by Trakt (and any future non-Stremio provider) where library data is
        obtained outside of the Stremio bundle.
        """
        await user_cache.set_library_items(token, library_items)
        logger.debug(f"[{redact_token(token)}] Cached library items (provider-agnostic)")

        language = user_settings.language
        tmdb_key = resolve_tmdb_api_key(user_settings)
        integration_service = ProfileIntegration(language=language, tmdb_api_key=tmdb_key)

        for content_type in ["movie", "series"]:
            try:
                profile, watched_tmdb, watched_imdb = await integration_service.build_profile_from_library(
                    library_items, content_type
                )
                await user_cache.set_profile_and_watched_sets(token, content_type, profile, watched_tmdb, watched_imdb)
                logger.debug(f"[{redact_token(token)}] Cached profile for {content_type}")
            except Exception as e:
                logger.warning(f"[{redact_token(token)}] Failed to cache profile for {content_type}: {e}")


    async def _ensure_library_and_profiles_cached(
        self, bundle: StremioBundle, auth_key: str, user_settings: UserSettings, token: str
    ) -> dict[str, Any]:
        """Ensure library items and profiles are cached, fetching and building if needed."""
        # Try to get cached library items first
        library_items = await user_cache.get_library_items(token)

        if library_items:
            logger.debug(f"[{redact_token(token)}] Using cached library items for manifest")
            return library_items

        # If not cached, fetch and cache
        logger.info(f"[{redact_token(token)}] Library items not cached, fetching from Stremio for manifest")
        return await self.cache_library_and_profiles(bundle, auth_key, user_settings, token)

    async def _build_dynamic_catalogs(
        self, bundle: StremioBundle, auth_key: str, user_settings: UserSettings | None, token: str
    ) -> list[dict[str, Any]]:
        """Build dynamic catalogs for the manifest."""
        # check if cached, if not, fetch and cache
        library_items = await user_cache.get_library_items(token)
        if not library_items:
            library_items = await self._ensure_library_and_profiles_cached(bundle, auth_key, user_settings, token)
            await user_cache.set_library_items(token, library_items)

        tmdb_key = resolve_tmdb_api_key(user_settings)
        dynamic_catalog_service = DynamicCatalogService(language=user_settings.language, tmdb_api_key=tmdb_key)
        return await dynamic_catalog_service.get_dynamic_catalogs(library_items, user_settings, token=token)

    async def _translate_catalogs(self, catalogs: list[dict[str, Any]], language: str | None) -> list[dict[str, Any]]:
        """Translate catalog names to target language."""
        if not language:
            return catalogs

        translated_catalogs = []
        for cat in catalogs:
            await apply_catalog_translation(cat, language)
            translated_catalogs.append(cat)

        return translated_catalogs

    def _sort_catalogs(
        self, catalogs: list[dict[str, Any]], user_settings: UserSettings | None
    ) -> list[dict[str, Any]]:
        """Sort catalogs according to user settings order."""
        if not user_settings:
            return catalogs

        return sort_catalogs(catalogs, user_settings)

    async def _build_dynamic_catalogs_trakt(
        self, creds: dict, user_settings: UserSettings | None, token: str
    ) -> list[dict[str, Any]]:
        """Build dynamic catalogs for a Trakt-backed account."""
        from app.core.config import settings as app_settings
        from app.services.trakt.service import TraktBundle

        # Use cached library if available
        library_items = await user_cache.get_library_items(token)
        if not library_items:
            access_token = creds.get("authKey")  # stored as authKey after encryption/decryption
            if not access_token or not app_settings.TRAKT_CLIENT_ID or not app_settings.TRAKT_CLIENT_SECRET:
                logger.warning(f"[{redact_token(token)}] Trakt credentials missing, cannot fetch library")
                return []
            redirect_uri = f"{app_settings.HOST_NAME}/tokens/trakt/callback"
            trakt_bundle = TraktBundle(
                client_id=app_settings.TRAKT_CLIENT_ID,
                client_secret=app_settings.TRAKT_CLIENT_SECRET,
                redirect_uri=redirect_uri,
                access_token=access_token,
            )
            try:
                library_items = await trakt_bundle.library.get_library_items()
                await user_cache.set_library_items(token, library_items)
            finally:
                await trakt_bundle.close()

        if not library_items:
            return []

        tmdb_key = resolve_tmdb_api_key(user_settings)
        dynamic_catalog_service = DynamicCatalogService(
            language=user_settings.language if user_settings else "en-US",
            tmdb_api_key=tmdb_key,
        )
        return await dynamic_catalog_service.get_dynamic_catalogs(library_items, user_settings, token=token)

    async def get_manifest_for_token(self, token: str) -> dict[str, Any]:
        """
        Generate manifest for a given token.

        Args:
            token: User token

        Returns:
            Complete manifest dictionary

        Raises:
            HTTPException: If token is invalid or credentials are missing
        """
        if not token:
            raise HTTPException(status_code=401, detail="Missing token. Please reconfigure the addon.")

        # Load user credentials and settings
        creds = await token_store.get_user_data(token)
        if not creds:
            raise HTTPException(status_code=401, detail="Token not found. Please reconfigure the addon.")

        user_settings = None
        try:
            if creds.get("settings"):
                user_settings = UserSettings(**creds["settings"])
        except Exception as e:
            logger.error(f"[{redact_token(token)}] Error loading user data from token store: {e}")
            raise HTTPException(status_code=401, detail="Invalid token session. Please reconfigure.")

        base_manifest = self.get_base_manifest()

        fetched_catalogs = []
        try:
            if creds.get("auth_provider") == "trakt":
                # Trakt-backed account: fetch library from Trakt, bypass Stremio
                fetched_catalogs = await self._build_dynamic_catalogs_trakt(creds, user_settings, token)
            else:
                bundle = StremioBundle()
                try:
                    # Resolve auth key
                    auth_key = await self._resolve_auth_key(bundle, creds, token)

                    if auth_key:
                        fetched_catalogs = await self._build_dynamic_catalogs(bundle, auth_key, user_settings, token)
                finally:
                    await bundle.close()
        except Exception as e:
            logger.exception(f"[{redact_token(token)}] Dynamic catalog build failed: {e}")
            fetched_catalogs = []

        # Combine base catalogs with fetched catalogs
        all_catalogs = [c.copy() for c in base_manifest["catalogs"]] + [c.copy() for c in fetched_catalogs]

        # Translate catalogs
        language = user_settings.language if user_settings else None
        translated_catalogs = await self._translate_catalogs(all_catalogs, language)

        # Sort catalogs
        sorted_catalogs = self._sort_catalogs(translated_catalogs, user_settings)

        if sorted_catalogs:
            base_manifest["catalogs"] = sorted_catalogs

        return base_manifest


manifest_service = ManifestService()
