import random
import re
from typing import Any

from fastapi import HTTPException
from loguru import logger

from app.core.config import settings
from app.core.constants import DEFAULT_CATALOG_LIMIT, DEFAULT_MIN_ITEMS
from app.core.security import redact_token
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
from app.services.user_cache import user_cache
from app.utils.catalog import cache_profile_and_watched_sets


def should_shuffle(user_settings: UserSettings, catalog_id: str) -> bool:
    config = next((c for c in user_settings.catalogs if c.id == catalog_id), None)
    return getattr(config, "shuffle", False) if config else False


def shuffle_data_if_needed(
    user_settings: UserSettings, catalog_id: str, data: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    if should_shuffle(user_settings, catalog_id):
        random.shuffle(data)
    return data


def _clean_meta(meta: dict) -> dict:
    """Return a sanitized Stremio meta object without internal fields.

    Keeps only public keys and drops internal scoring/IDs/keywords/cast, etc.
    """
    allowed = {
        "id",
        "type",
        "name",
        "poster",
        "background",
        "description",
        "releaseInfo",
        "imdbRating",
        "genres",
        "runtime",
    }
    cleaned = {k: v for k, v in meta.items() if k in allowed}
    # Drop empty values
    cleaned = {k: v for k, v in cleaned.items() if v not in (None, "", [], {}, ())}

    # if id does not start with tt, return None
    if not cleaned.get("id", "").startswith("tt"):
        return None
    return cleaned


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

        # Prepare response headers
        headers: dict[str, Any] = {"Cache-Control": f"public, max-age={settings.CATALOG_CACHE_TTL}"}

        logger.info(f"[{redact_token(token)}...] Fetching catalog for {content_type} with id {catalog_id}")

        # Get credentials
        credentials = await token_store.get_user_data(token)
        if not credentials:
            logger.error("No credentials found for token")
            raise HTTPException(status_code=401, detail="Invalid or expired token. Please reconfigure the addon.")

        # Trigger lazy update if needed
        if settings.AUTO_UPDATE_CATALOGS:
            logger.info(f"[{redact_token(token)}...] Triggering auto update for token")
            try:
                await catalog_updater.trigger_update(token, credentials)
            except Exception as e:
                logger.error(f"[{redact_token(token)}...] Failed to trigger auto update: {e}")
                # continue with the request even if the auto update fails
                pass

        bundle = StremioBundle()
        # Resolve auth and settings
        auth_key = await self._resolve_auth(bundle, credentials, token)
        user_settings = self._extract_settings(credentials)

        # get cached catalog
        cached_data = await user_cache.get_catalog(token, content_type, catalog_id)
        if cached_data:
            logger.debug(f"[{redact_token(token)}...] Using cached catalog for {content_type}/{catalog_id}")
            meta_data = cached_data["metas"]
            meta_data = shuffle_data_if_needed(user_settings, catalog_id, meta_data)
            cached_data["metas"] = meta_data
            return cached_data, headers

        logger.info(
            f"[{redact_token(token)}...] Catalog not cached for {content_type}/{catalog_id}, building from" " scratch"
        )

        try:
            language = user_settings.language if user_settings else "en-US"

            # Try to get cached library items first
            library_items = await user_cache.get_library_items(token)

            if library_items:
                logger.debug(f"[{redact_token(token)}...] Using cached library items")
            else:
                # Fetch library if not cached
                logger.info(f"[{redact_token(token)}...] Library items not cached, fetching from Stremio")
                library_items = await bundle.library.get_library_items(auth_key)
                # Cache it for future use
                await user_cache.set_library_items(token, library_items)

            services = self._initialize_services(language, user_settings)
            integration_service: ProfileIntegration = services["integration"]

            # Try to get cached profile and watched sets
            cached_data = await user_cache.get_profile_and_watched_sets(token, content_type)

            if cached_data:
                # Use cached profile and watched sets
                profile, watched_tmdb, watched_imdb = cached_data
                logger.debug(f"[{redact_token(token)}...] Using cached profile and watched sets for {content_type}")
            else:
                # Build profile if not cached
                logger.info(f"[{redact_token(token)}...] Profile not cached for {content_type}, building from library")
                profile, watched_tmdb, watched_imdb = await cache_profile_and_watched_sets(
                    token, content_type, integration_service, library_items, bundle, auth_key
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

            # Clean and format metadata
            cleaned = [_clean_meta(m) for m in recommendations]
            cleaned = [m for m in cleaned if m is not None]

            cleaned = shuffle_data_if_needed(user_settings, catalog_id, cleaned)

            data = {"metas": cleaned}
            # if catalog data is not empty, set the cache
            if cleaned:
                await user_cache.set_catalog(token, content_type, catalog_id, data, settings.CATALOG_CACHE_TTL)

            return data, headers

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
