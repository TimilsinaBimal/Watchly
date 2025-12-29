import re
from typing import Any

from fastapi import HTTPException
from loguru import logger

from app.core.config import settings
from app.core.constants import DEFAULT_CATALOG_LIMIT, DEFAULT_MIN_ITEMS
from app.core.settings import UserSettings, get_default_settings
from app.models.taste_profile import TasteProfile
from app.services.catalog_updater import catalog_updater
from app.services.profile.integration import ProfileIntegration
from app.services.recommendation.all_based import AllBasedService
from app.services.recommendation.creators import CreatorsService
from app.services.recommendation.item_based import ItemBasedService
from app.services.recommendation.theme_based import ThemeBasedService
from app.services.recommendation.top_picks import TopPicksService
from app.services.recommendation.utils import pad_to_min
from app.services.stremio.service import StremioBundle
from app.services.tmdb.service import get_tmdb_service
from app.services.token_store import token_store

PAD_RECOMMENDATIONS_THRESHOLD = 8
PAD_RECOMMENDATIONS_TARGET = 10


class CatalogService:
    def __init__(self):
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
        # Validate inputs
        self._validate_inputs(token, content_type, catalog_id)

        logger.info(f"[{token[:8]}...] Fetching catalog for {content_type} with id {catalog_id}")

        # Get credentials
        credentials = await token_store.get_user_data(token)
        if not credentials:
            logger.error("No credentials found for token")
            raise HTTPException(status_code=401, detail="Invalid or expired token. Please reconfigure the addon.")

        # Trigger lazy update if needed
        if settings.AUTO_UPDATE_CATALOGS:
            logger.info(f"[{token[:8]}...] Triggering auto update for token")
            try:
                await catalog_updater.trigger_update(token, credentials)
            except Exception as e:
                logger.error(f"[{token[:8]}...] Failed to trigger auto update: {e}")
                # continue with the request even if the auto update fails
                pass

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

            integration_service: ProfileIntegration = services["integration"]

            # Build profile and watched sets (once, reused)
            profile, watched_tmdb, watched_imdb = await integration_service.build_profile_from_library(
                library_items, content_type, bundle, auth_key
            )
            whitelist = await integration_service.get_genre_whitelist(profile, content_type) if profile else set()

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
                limit=DEFAULT_CATALOG_LIMIT,
            )

            # Pad if needed to meet minimum of 8 items
            # # TODO: This is risky because it can fetch too many unrelated items.
            if recommendations and len(recommendations) < DEFAULT_MIN_ITEMS:
                recommendations = await pad_to_min(
                    content_type,
                    recommendations,
                    DEFAULT_MIN_ITEMS,
                    services["tmdb"],
                    user_settings,
                    watched_tmdb,
                    watched_imdb,
                )

            logger.info(f"Returning {len(recommendations)} items for {content_type}")

            # Prepare response headers
            headers = {"Cache-Control": f"public, max-age={settings.CATALOG_CACHE_TTL}"}

            return recommendations, headers

        finally:
            await bundle.close()

    def _validate_inputs(self, token: str, content_type: str, catalog_id: str) -> None:
        if not token:
            raise HTTPException(
                status_code=400,
                detail="Missing credentials token. Please open Watchly from a configured manifest URL.",
            )

        if content_type not in ["movie", "series"]:
            logger.warning(f"Invalid type: {content_type}")
            raise HTTPException(status_code=400, detail="Invalid type. Use 'movie' or 'series'")

        # Supported IDs
        supported_base = ["watchly.rec", "watchly.creators", "watchly.all.loved", "watchly.liked.all"]
        supported_prefixes = ("watchly.theme.", "watchly.loved.", "watchly.watched.")
        if catalog_id not in supported_base and not any(catalog_id.startswith(p) for p in supported_prefixes):
            logger.warning(f"Invalid id: {catalog_id}")
            raise HTTPException(
                status_code=400,
                detail=(
                    "Invalid id. Supported: 'watchly.rec', 'watchly.creators', "
                    "'watchly.theme.<params>', 'watchly.all.loved', 'watchly.liked.all'"
                ),
            )

    async def _resolve_auth(self, bundle: StremioBundle, credentials: dict, token: str) -> str:
        auth_key = credentials.get("authKey")
        email = credentials.get("email")
        password = credentials.get("password")

        # Validate existing auth key
        is_valid = False
        if auth_key:
            try:
                await bundle.auth.get_user_info(auth_key)
                is_valid = True
            except Exception as e:
                logger.error(f"Failed to validate auth key during catalog fetch: {e}")
                pass

        # Try to refresh if invalid
        if not is_valid and email and password:
            try:
                auth_key = await bundle.auth.login(email, password)
                credentials["authKey"] = auth_key
                # Update token store with refreshed credentials
                await token_store.update_user_data(token, credentials)
            except Exception as e:
                logger.error(f"Failed to refresh auth key during catalog fetch: {e}")

        if not auth_key:
            logger.error("No auth key found during catalog fetch")
            raise HTTPException(status_code=401, detail="Stremio session expired. Please reconfigure.")

        return auth_key

    def _extract_settings(self, credentials: dict) -> UserSettings:
        settings_dict = credentials.get("settings", {})
        return UserSettings(**settings_dict) if settings_dict else get_default_settings()

    def _initialize_services(self, language: str, user_settings: UserSettings) -> dict[str, Any]:
        tmdb_service = get_tmdb_service(language=language)
        return {
            "tmdb": tmdb_service,
            "integration": ProfileIntegration(language=language),
            "item": ItemBasedService(tmdb_service, user_settings),
            "theme": ThemeBasedService(tmdb_service, user_settings),
            "top_picks": TopPicksService(tmdb_service, user_settings),
            "creators": CreatorsService(tmdb_service, user_settings),
            "all_based": AllBasedService(tmdb_service, user_settings),
        }

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
        limit: int,
    ) -> list[dict[str, Any]]:
        """Route to appropriate recommendation service based on catalog ID."""
        # Item-based recommendations
        if any(
            catalog_id.startswith(p)
            for p in (
                "watchly.loved.",
                "watchly.watched.",
            )
        ):
            # Extract item ID
            item_id = re.sub(r"^watchly\.(loved|watched)\.", "", catalog_id)

            item_service: ItemBasedService = services["item"]

            recommendations = await item_service.get_recommendations_for_item(
                item_id=item_id,
                content_type=content_type,
                watched_tmdb=watched_tmdb,
                watched_imdb=watched_imdb,
                limit=limit,
                whitelist=whitelist,
            )
            logger.info(f"Found {len(recommendations)} recommendations for item {item_id}")

        # Theme-based recommendations
        elif catalog_id.startswith("watchly.theme."):
            theme_service: ThemeBasedService = services["theme"]

            recommendations = await theme_service.get_recommendations_for_theme(
                theme_id=catalog_id,
                content_type=content_type,
                profile=profile,
                watched_tmdb=watched_tmdb,
                watched_imdb=watched_imdb,
                limit=limit,
                whitelist=whitelist,
            )
            logger.info(f"Found {len(recommendations)} recommendations for theme {catalog_id}")

        # Creators-based recommendations
        elif catalog_id == "watchly.creators":
            creators_service: CreatorsService = services["creators"]

            if profile:
                recommendations = await creators_service.get_recommendations_from_creators(
                    profile=profile,
                    content_type=content_type,
                    watched_tmdb=watched_tmdb,
                    watched_imdb=watched_imdb,
                    limit=limit,
                )
            else:
                recommendations = []
            logger.info(f"Found {len(recommendations)} recommendations from creators")

        # Top picks
        elif catalog_id == "watchly.rec":
            if profile:
                top_picks_service: TopPicksService = services["top_picks"]

                recommendations = await top_picks_service.get_top_picks(
                    profile=profile,
                    content_type=content_type,
                    library_items=library_items,
                    watched_tmdb=watched_tmdb,
                    watched_imdb=watched_imdb,
                    limit=limit,
                )
            else:
                recommendations = []
            logger.info(f"Found {len(recommendations)} top picks for {content_type}")

        # Based on what you loved
        elif catalog_id in ("watchly.all.loved", "watchly.liked.all"):
            item_type = "loved" if catalog_id == "watchly.all.loved" else "liked"
            all_based_service: AllBasedService = services["all_based"]
            recommendations = await all_based_service.get_recommendations_from_all_items(
                library_items=library_items,
                content_type=content_type,
                watched_tmdb=watched_tmdb,
                watched_imdb=watched_imdb,
                whitelist=whitelist,
                limit=limit,
                item_type=item_type,
                profile=profile,
            )
            logger.info(f"Found {len(recommendations)} recommendations based on all {item_type} items")

        else:
            logger.warning(f"Unknown catalog ID: {catalog_id}")
            recommendations = []

        return recommendations


catalog_service = CatalogService()
