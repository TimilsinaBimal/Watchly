"""
Catalog Service - Facade for catalog generation.

Encapsulates all catalog logic: auth, profile building, routing, and recommendations.
"""

import re
from typing import Any

from loguru import logger

from app.api.endpoints.manifest import get_config_id
from app.core.config import settings
from app.core.settings import UserSettings, get_default_settings
from app.models.taste_profile import TasteProfile
from app.services.catalog_updater import catalog_updater
from app.services.profile.integration import ProfileIntegration
from app.services.recommendation.creators import CreatorsService
from app.services.recommendation.item_based import ItemBasedService
from app.services.recommendation.theme_based import ThemeBasedService
from app.services.recommendation.top_picks import TopPicksService
from app.services.recommendation.utils import pad_to_min
from app.services.stremio.service import StremioBundle
from app.services.tmdb.service import get_tmdb_service
from app.services.token_store import token_store

DEFAULT_MIN_ITEMS = 20
DEFAULT_MAX_ITEMS = 32


class CatalogService:
    """
    Facade for catalog generation.

    Handles all catalog logic: validation, auth, profile building, routing, and recommendations.
    """

    def __init__(self):
        """Initialize catalog service."""
        pass

    async def get_catalog(
        self, token: str, content_type: str, catalog_id: str
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """
        Get catalog recommendations.

        Args:
            token: User token
            content_type: Content type (movie/series)
            catalog_id: Catalog ID (watchly.rec, watchly.creators, watchly.theme.*, etc.)

        Returns:
            Tuple of (recommendations list, response headers dict)
        """
        """
        Get catalog recommendations.

        Args:
            token: User token
            content_type: Content type (movie/series)
            catalog_id: Catalog ID (watchly.rec, watchly.creators, watchly.theme.*, etc.)

        Returns:
            Tuple of (recommendations list, response headers dict)
        """
        # Validate inputs
        self._validate_inputs(token, content_type, catalog_id)

        logger.info(f"[{token[:8]}...] Fetching catalog for {content_type} with id {catalog_id}")

        # Get credentials
        credentials = await token_store.get_user_data(token)
        if not credentials:
            from fastapi import HTTPException

            raise HTTPException(status_code=401, detail="Invalid or expired token. Please reconfigure the addon.")

        # Trigger lazy update if needed
        if settings.AUTO_UPDATE_CATALOGS:
            await catalog_updater.trigger_update(token, credentials)

        bundle = StremioBundle()
        try:
            # Resolve auth and settings
            auth_key = await self._resolve_auth(bundle, credentials, token)
            user_settings = self._extract_settings(credentials)
            language = user_settings.language if user_settings else "en-US"

            # Fetch library
            library_items = await bundle.library.get_library_items(auth_key)

            # Initialize services
            services = self._initialize_services(language, user_settings)

            # Build profile and watched sets (once, reused)
            profile, watched_tmdb, watched_imdb = await services["integration"].build_profile_from_library(
                library_items, content_type, bundle, auth_key
            )
            whitelist = await services["integration"].get_genre_whitelist(profile, content_type) if profile else set()

            # Get catalog limits
            min_items, max_items = self._get_catalog_limits(catalog_id, user_settings)

            # Route to appropriate recommendation service
            recommendations = await self._get_recommendations(
                catalog_id=catalog_id,
                content_type=content_type,
                services=services,
                profile=profile,
                watched_tmdb=watched_tmdb,
                watched_imdb=watched_imdb,
                whitelist=whitelist,
                library_items=library_items,
                max_items=max_items,
            )

            # Pad if needed
            if len(recommendations) < min_items:
                recommendations = await pad_to_min(
                    content_type,
                    recommendations,
                    min_items,
                    services["tmdb"],
                    user_settings,
                    watched_tmdb,
                    watched_imdb,
                )

            logger.info(f"Returning {len(recommendations)} items for {content_type}")

            # Prepare response headers
            headers = {"Cache-Control": "public, max-age=21600"}  # 6 hours

            return recommendations, headers

        finally:
            await bundle.close()

    def _validate_inputs(self, token: str, content_type: str, catalog_id: str) -> None:
        """Validate input parameters."""
        from fastapi import HTTPException

        if not token:
            raise HTTPException(
                status_code=400,
                detail="Missing credentials token. Please open Watchly from a configured manifest URL.",
            )

        if content_type not in ["movie", "series"]:
            logger.warning(f"Invalid type: {content_type}")
            raise HTTPException(status_code=400, detail="Invalid type. Use 'movie' or 'series'")

        # Supported IDs
        if catalog_id not in ["watchly.rec", "watchly.creators"] and not any(
            catalog_id.startswith(p)
            for p in (
                "tt",
                "watchly.theme.",
                "watchly.item.",
                "watchly.loved.",
                "watchly.watched.",
            )
        ):
            logger.warning(f"Invalid id: {catalog_id}")
            raise HTTPException(
                status_code=400,
                detail=(
                    "Invalid id. Supported: 'watchly.rec', 'watchly.creators', 'watchly.theme.<params>',"
                    "'watchly.item.<id>', or specific item IDs."
                ),
            )

    async def _resolve_auth(self, bundle: StremioBundle, credentials: dict, token: str) -> str:
        """Resolve and validate auth key."""
        from fastapi import HTTPException

        auth_key = credentials.get("authKey")
        email = credentials.get("email")
        password = credentials.get("password")

        # Validate existing auth key
        is_valid = False
        if auth_key:
            try:
                await bundle.auth.get_user_info(auth_key)
                is_valid = True
            except Exception:
                pass

        # Try to refresh if invalid
        if not is_valid and email and password:
            try:
                auth_key = await bundle.auth.login(email, password)
                credentials["authKey"] = auth_key
                # Note: token is not stored in credentials, we'd need to pass it separately
                # For now, this is handled by the caller if needed
                pass
            except Exception as e:
                logger.error(f"Failed to refresh auth key during catalog fetch: {e}")

        if not auth_key:
            raise HTTPException(status_code=401, detail="Stremio session expired. Please reconfigure.")

        return auth_key

    def _extract_settings(self, credentials: dict) -> UserSettings:
        """Extract user settings from credentials."""
        settings_dict = credentials.get("settings", {})
        return UserSettings(**settings_dict) if settings_dict else get_default_settings()

    def _initialize_services(self, language: str, user_settings: UserSettings) -> dict[str, Any]:
        """Initialize all recommendation services."""
        tmdb_service = get_tmdb_service(language=language)
        integration = ProfileIntegration(language=language)

        return {
            "tmdb": tmdb_service,
            "integration": integration,
            "item": ItemBasedService(tmdb_service, user_settings),
            "theme": ThemeBasedService(tmdb_service, user_settings),
            "top_picks": TopPicksService(tmdb_service, user_settings),
            "creators": CreatorsService(tmdb_service, user_settings),
        }

    def _get_catalog_limits(self, catalog_id: str, user_settings: UserSettings) -> tuple[int, int]:
        """Get min/max items for catalog."""
        try:
            cfg_id = get_config_id({"id": catalog_id})
        except Exception:
            cfg_id = catalog_id

        try:
            cfg = next((c for c in user_settings.catalogs if c.id == cfg_id), None)
            if cfg and hasattr(cfg, "min_items") and hasattr(cfg, "max_items"):
                min_items = int(cfg.min_items or DEFAULT_MIN_ITEMS)
                max_items = int(cfg.max_items or DEFAULT_MAX_ITEMS)
            else:
                min_items, max_items = DEFAULT_MIN_ITEMS, DEFAULT_MAX_ITEMS
        except Exception:
            min_items, max_items = DEFAULT_MIN_ITEMS, DEFAULT_MAX_ITEMS

        # Enforce caps
        try:
            min_items = max(1, min(DEFAULT_MIN_ITEMS, int(min_items)))
            max_items = max(min_items, min(DEFAULT_MAX_ITEMS, int(max_items)))
        except (ValueError, TypeError):
            logger.warning(
                f"Invalid min/max items values. Falling back to defaults. "
                f"min_items={min_items}, max_items={max_items}"
            )
            min_items, max_items = DEFAULT_MIN_ITEMS, DEFAULT_MAX_ITEMS

        return min_items, max_items

    async def _get_recommendations(
        self,
        catalog_id: str,
        content_type: str,
        services: dict[str, Any],
        profile: TasteProfile | None,
        watched_tmdb: set[int],
        watched_imdb: set[str],
        whitelist: set[int],
        library_items: dict,
        max_items: int,
    ) -> list[dict[str, Any]]:
        """Route to appropriate recommendation service based on catalog ID."""
        # Item-based recommendations
        if catalog_id.startswith("tt") or any(
            catalog_id.startswith(p)
            for p in (
                "watchly.item.",
                "watchly.loved.",
                "watchly.watched.",
            )
        ):
            # Extract item ID
            if catalog_id.startswith("tt"):
                item_id = catalog_id
            else:
                item_id = re.sub(r"^watchly\.(item|loved|watched)\.", "", catalog_id)

            recommendations = await services["item"].get_recommendations_for_item(
                item_id=item_id,
                content_type=content_type,
                watched_tmdb=watched_tmdb,
                watched_imdb=watched_imdb,
                limit=max_items,
                whitelist=whitelist,
            )
            logger.info(f"Found {len(recommendations)} recommendations for item {item_id}")

        # Theme-based recommendations
        elif catalog_id.startswith("watchly.theme."):
            recommendations = await services["theme"].get_recommendations_for_theme(
                theme_id=catalog_id,
                content_type=content_type,
                profile=profile,
                watched_tmdb=watched_tmdb,
                watched_imdb=watched_imdb,
                limit=max_items,
                whitelist=whitelist,
            )
            logger.info(f"Found {len(recommendations)} recommendations for theme {catalog_id}")

        # Creators-based recommendations
        elif catalog_id == "watchly.creators":
            if profile:
                recommendations = await services["creators"].get_recommendations_from_creators(
                    profile=profile,
                    content_type=content_type,
                    library_items=library_items,
                    watched_tmdb=watched_tmdb,
                    watched_imdb=watched_imdb,
                    whitelist=whitelist,
                    limit=max_items,
                )
            else:
                recommendations = []
            logger.info(f"Found {len(recommendations)} recommendations from creators")

        # Top picks
        elif catalog_id == "watchly.rec":
            if profile:
                recommendations = await services["top_picks"].get_top_picks(
                    profile=profile,
                    content_type=content_type,
                    library_items=library_items,
                    watched_tmdb=watched_tmdb,
                    watched_imdb=watched_imdb,
                    limit=max_items,
                )
            else:
                recommendations = []
            logger.info(f"Found {len(recommendations)} top picks for {content_type}")

        else:
            logger.warning(f"Unknown catalog ID: {catalog_id}")
            recommendations = []

        return recommendations
