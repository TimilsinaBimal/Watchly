import copy
from typing import Any

from loguru import logger

from app.core.config import settings
from app.core.security import redact_token
from app.core.settings import UserSettings, resolve_tmdb_api_key
from app.core.version import __version__
from app.models.library import LibraryCollection
from app.services.catalog_definitions import DynamicCatalogService, sort_catalogs
from app.services.context import fetch_library_for_source, load_user_context
from app.services.profile.service import ProfileService
from app.services.stremio.service import StremioBundle
from app.services.translation import apply_catalog_translation
from app.services.user_cache import user_cache


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
            "logo": ("https://raw.githubusercontent.com/TimilsinaBimal/Watchly" "/refs/heads/main/app/static/logo.png"),
            "background": (
                "https://raw.githubusercontent.com/TimilsinaBimal/Watchly" "/refs/heads/main/app/static/cover.png"
            ),
            "resources": ["catalog"],
            "types": ["movie", "series"],
            "idPrefixes": ["tt"],
            "catalogs": [],
            "behaviorHints": {"configurable": True, "configurationRequired": False},
            "stremioAddonsConfig": {
                "issuer": "https://stremio-addons.net",
                "signature": (
                    "eyJhbGciOiJkaXIiLCJlbmMiOiJBMTI4Q0JDLUhTMjU2In0"
                    "..WSrhzzlj1TuDycD6QoVLuA"
                    ".Dzmxzr4y83uqQF15r4tC1bB9-vtZRh1Rvy4BqgDYxu91c2esiJuov9KnnI_cboQC"
                    "gZS7hjwnIqRSlQ-jEyGwXHHRerh9QklyfdxpXqNUyBgTWFzDOVdVvDYJeM_tGMmR"
                    ".sezAChlWGV7lNS-t9HWB6A"  # noqa
                ),
            },
        }

    async def cache_library_and_profiles(
        self,
        bundle: StremioBundle,
        auth_key: str,
        user_settings: UserSettings,
        token: str,
    ) -> LibraryCollection:
        """Fetch and cache library items and profiles for a user.

        Called during token creation to pre-cache data so manifest generation is fast.
        """
        # Cache the library from the user's configured source (Trakt/Simkl/Stremio),
        # not always Stremio. Tagging the bootstrap cache as "stremio" for a Trakt/
        # Simkl user made load_user_context see a source mismatch and re-fetch the
        # whole external history on every manifest request (#144).
        source = user_settings.watch_history_source
        logger.info(f"[{redact_token(token)}] Fetching library items from '{source}' for caching")
        library_items = await fetch_library_for_source(source, user_settings, token, bundle, auth_key)
        if library_items is None:
            library_items = LibraryCollection()
        await user_cache.set_library_items(token, library_items)
        logger.debug(f"[{redact_token(token)}] Cached library items (source={library_items.source})")

        language = user_settings.language
        tmdb_key = resolve_tmdb_api_key(user_settings)
        profile_service = ProfileService(language=language, tmdb_api_key=tmdb_key)

        for content_type in ["movie", "series"]:
            try:
                logger.info(f"[{redact_token(token)}] Building and caching profile for {content_type}")
                await profile_service.build_and_cache_profile(
                    token, content_type, library_items, bundle, auth_key, user_settings=user_settings
                )
                logger.debug(f"[{redact_token(token)}] Cached profile and watched sets for {content_type}")
            except Exception as e:
                logger.warning(f"[{redact_token(token)}] Failed to build/cache profile for {content_type}: {e}")

        return library_items

    async def get_manifest_for_token(self, token: str) -> dict[str, Any]:
        """Generate manifest for a given token."""
        base_manifest = self.get_base_manifest()

        ctx = await load_user_context(token, require_auth=False)
        fetched_catalogs: list[dict[str, Any]] = []
        try:
            if ctx.auth_key:
                tmdb_key = resolve_tmdb_api_key(ctx.user_settings)
                catalog_def_service = DynamicCatalogService(language=ctx.user_settings.language, tmdb_api_key=tmdb_key)
                fetched_catalogs = await catalog_def_service.get_dynamic_catalogs(
                    ctx.library, ctx.user_settings, token=token
                )
        except Exception as e:
            logger.exception(f"[{redact_token(token)}] Dynamic catalog build failed: {e}")
            fetched_catalogs = []
        finally:
            await ctx.close()

        # deepcopy: catalogs contain nested dicts/lists (extra params, options) that
        # downstream code mutates (translation, sort). Shallow copies would mutate
        # shared inner objects across users.
        all_catalogs = [copy.deepcopy(c) for c in base_manifest["catalogs"]] + [
            copy.deepcopy(c) for c in fetched_catalogs
        ]

        language = ctx.user_settings.language
        translated = await self._translate_catalogs(all_catalogs, language)
        sorted_catalogs = sort_catalogs(translated, ctx.user_settings)

        if sorted_catalogs:
            base_manifest["catalogs"] = sorted_catalogs

        return base_manifest

    async def _translate_catalogs(self, catalogs: list[dict[str, Any]], language: str | None) -> list[dict[str, Any]]:
        """Translate catalog names to target language."""
        if not language:
            return catalogs

        translated_catalogs = []
        for cat in catalogs:
            await apply_catalog_translation(cat, language)
            translated_catalogs.append(cat)

        return translated_catalogs


manifest_service = ManifestService()
