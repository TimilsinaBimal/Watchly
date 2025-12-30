from typing import Any

from fastapi import HTTPException
from loguru import logger

from app.core.config import settings
from app.core.security import redact_token
from app.core.settings import UserSettings
from app.core.version import __version__
from app.services.catalog import DynamicCatalogService
from app.services.profile.integration import ProfileIntegration
from app.services.stremio.service import StremioBundle
from app.services.token_store import token_store
from app.services.translation import translation_service
from app.services.user_cache import user_cache
from app.utils.catalog import cache_profile_and_watched_sets, get_config_id


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
        integration_service = ProfileIntegration(language=language)

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
        # Ensure library and profiles are cached
        library_items = await self._ensure_library_and_profiles_cached(bundle, auth_key, user_settings, token)

        dynamic_catalog_service = DynamicCatalogService(language=user_settings.language)
        return await dynamic_catalog_service.get_dynamic_catalogs(library_items, user_settings)

    async def _translate_catalogs(self, catalogs: list[dict[str, Any]], language: str | None) -> list[dict[str, Any]]:
        """Translate catalog names to target language."""
        if not language:
            return catalogs

        translated_catalogs = []
        for cat in catalogs:
            if cat.get("name"):
                try:
                    cat["name"] = await translation_service.translate(cat["name"], language)
                except Exception as e:
                    logger.warning(f"Failed to translate catalog name '{cat.get('name')}': {e}")
            translated_catalogs.append(cat)

        return translated_catalogs

    def _sort_catalogs(
        self, catalogs: list[dict[str, Any]], user_settings: UserSettings | None
    ) -> list[dict[str, Any]]:
        """Sort catalogs according to user settings order."""
        if not user_settings:
            return catalogs

        order_map = {c.id: i for i, c in enumerate(user_settings.catalogs)}
        sorted_catalogs = sorted(catalogs, key=lambda x: order_map.get(get_config_id(x), 999))
        return sorted_catalogs

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

        bundle = StremioBundle()
        fetched_catalogs = []
        try:
            # Resolve auth key
            auth_key = await self._resolve_auth_key(bundle, creds, token)

            if auth_key:
                fetched_catalogs = await self._build_dynamic_catalogs(bundle, auth_key, user_settings, token)
        except Exception as e:
            logger.exception(f"[{redact_token(token)}] Dynamic catalog build failed: {e}")
            fetched_catalogs = []
        finally:
            await bundle.close()

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
