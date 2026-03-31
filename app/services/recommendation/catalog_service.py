import re
import time
from typing import Any

from fastapi import HTTPException
from loguru import logger

from app.core.config import settings
from app.core.constants import DEFAULT_CATALOG_LIMIT
from app.core.security import redact_token
from app.core.settings import UserSettings, resolve_tmdb_api_key
from app.models.library import LibraryCollection
from app.models.profile import TasteProfile
from app.services.catalog_updater import catalog_updater
from app.services.context import UserContext, extract_settings, load_user_context
from app.services.profile.service import ProfileService
from app.services.recommendation.all_based import AllBasedService
from app.services.recommendation.catalog_utils import clean_meta, shuffle_data_if_needed
from app.services.recommendation.creators import CreatorsService
from app.services.recommendation.item_based import ItemBasedService
from app.services.recommendation.theme_based import ThemeBasedService
from app.services.recommendation.top_picks import TopPicksService
from app.services.tmdb.service import get_tmdb_service
from app.services.token_store import token_store
from app.services.user_cache import user_cache


class CatalogService:
    async def get_catalog(
        self, token: str, content_type: str, catalog_id: str
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Get catalog recommendations."""
        self._validate_inputs(token, content_type, catalog_id)

        headers: dict[str, Any] = {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "*",
            "Content-Type": "application/json",
            "Cache-Control": (
                f"public, max-age={settings.CATALOG_CACHE_TTL},stale-while-revalidate=3600, stale-if-error=1800"
            ),
        }

        logger.info(f"[{redact_token(token)}] Fetching catalog for {content_type} with id {catalog_id}")

        # Load credentials (needed for cache check + shuffle settings)
        credentials = await token_store.get_user_data(token)
        if not credentials:
            logger.error("No credentials found for token")
            raise HTTPException(
                status_code=401,
                detail="Invalid or expired token. Please reconfigure the addon.",
            )

        # Trigger lazy update if needed
        if settings.AUTO_UPDATE_CATALOGS:
            try:
                await catalog_updater.trigger_update(token, credentials)
            except Exception as e:
                logger.error(f"[{redact_token(token)}] Failed to trigger auto update: {e}")

        # Check cache first — avoids auth/library/profile loading on cache hit
        stale_data = None
        cached_result = await user_cache.get_catalog(token, content_type, catalog_id)

        if cached_result:
            data, created_at = cached_result
            age = int(time.time()) - created_at

            if age < settings.CATALOG_REFRESH_INTERVAL_SECONDS:
                logger.debug(f"[{redact_token(token)}] Using cached catalog for {content_type}/{catalog_id}")
                user_settings = extract_settings(credentials)
                data["metas"] = shuffle_data_if_needed(user_settings, catalog_id, data["metas"])
                return data, headers

            stale_data = data
            logger.info(
                f"[{redact_token(token)}] Catalog stale (age: {age}s) for "
                f"{content_type}/{catalog_id}, refreshing..."
            )
        else:
            logger.info(
                f"[{redact_token(token)}] Catalog not cached for " f"{content_type}/{catalog_id}, building from scratch"
            )

        # Cache miss — load full user context
        ctx = await load_user_context(token)
        try:
            return await self._build_catalog(ctx, content_type, catalog_id, headers, stale_data)
        finally:
            await ctx.close()

    async def _build_catalog(
        self,
        ctx: UserContext,
        content_type: str,
        catalog_id: str,
        headers: dict[str, Any],
        stale_data: dict[str, Any] | None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Build fresh catalog content using the loaded user context."""
        try:
            services = self._initialize_services(ctx.user_settings)
            profile_service: ProfileService = services["profile"]

            # Load profile (cached or build fresh)
            cached_data = await user_cache.get_profile_and_watched_sets(ctx.token, content_type)

            if cached_data:
                profile, watched_tmdb, watched_imdb = cached_data
                logger.debug(f"[{redact_token(ctx.token)}] Using cached profile for {content_type}")
            else:
                logger.info(f"[{redact_token(ctx.token)}] Profile not cached for {content_type}, building")
                profile, watched_tmdb, watched_imdb = await profile_service.build_and_cache_profile(
                    ctx.token,
                    content_type,
                    ctx.library,
                    ctx.bundle,
                    ctx.auth_key,
                )

            recommendations = await self._get_recommendations(
                catalog_id=catalog_id,
                content_type=content_type,
                services=services,
                profile=profile,
                watched_tmdb=watched_tmdb,
                watched_imdb=watched_imdb,
                library_items=ctx.library,
                limit=DEFAULT_CATALOG_LIMIT,
                user_settings=ctx.user_settings,
            )

            logger.info(f"Returning {len(recommendations)} items for {content_type}")

            cleaned = [m for m in (clean_meta(m) for m in recommendations) if m is not None]
            cleaned = shuffle_data_if_needed(ctx.user_settings, catalog_id, cleaned)

            data = {"metas": cleaned}
            if cleaned:
                await user_cache.set_catalog(ctx.token, content_type, catalog_id, data, settings.CATALOG_STALE_TTL)

            return data, headers

        except Exception as e:
            logger.error(f"[{redact_token(ctx.token)}] Failed to generate catalog: {e}")

            if stale_data:
                logger.warning(
                    f"[{redact_token(ctx.token)}] Serving stale content for "
                    f"{content_type}/{catalog_id} due to error"
                )
                meta_data = stale_data.get("metas", [])
                meta_data = shuffle_data_if_needed(ctx.user_settings, catalog_id, meta_data)
                stale_data["metas"] = meta_data
                return stale_data, headers

            return {"metas": []}, headers

    def _validate_inputs(self, token: str, content_type: str, catalog_id: str) -> None:
        if not token:
            raise HTTPException(
                status_code=400,
                detail="Missing credentials token. Please open Watchly from a configured manifest URL.",
            )

        if content_type not in ["movie", "series"]:
            logger.warning(f"Invalid type: {content_type}")
            raise HTTPException(status_code=400, detail="Invalid type. Use 'movie' or 'series'")

        supported_base = [
            "watchly.rec",
            "watchly.creators",
            "watchly.all.loved",
            "watchly.liked.all",
        ]
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

    def _initialize_services(self, user_settings: UserSettings) -> dict[str, Any]:
        tmdb_key = resolve_tmdb_api_key(user_settings)
        language = user_settings.language
        tmdb_service = get_tmdb_service(language=language, api_key=tmdb_key)
        return {
            "tmdb": tmdb_service,
            "profile": ProfileService(language=language, tmdb_api_key=tmdb_key),
            "item": ItemBasedService(tmdb_service, user_settings),
            "theme": ThemeBasedService(tmdb_service, user_settings),
            "top_picks": TopPicksService(tmdb_service, user_settings),
            "creators": CreatorsService(tmdb_service, user_settings),
            "all_based": AllBasedService(tmdb_service, user_settings),
        }

    async def _get_trending_fallback(
        self,
        content_type: str,
        limit: int = 20,
        user_settings: UserSettings | None = None,
    ) -> list[dict[str, Any]]:
        """Get trending items for new users without profiles."""
        from app.services.recommendation.utils import content_type_to_mtype

        mtype = content_type_to_mtype(content_type)
        tmdb_key = resolve_tmdb_api_key(user_settings)
        language = user_settings.language if user_settings else "en-US"
        tmdb_service = get_tmdb_service(language=language, api_key=tmdb_key)

        try:
            trending = await tmdb_service.get_trending(mtype, "week")
            items = trending.get("results", [])

            from app.services.recommendation.metadata import RecommendationMetadata

            return await RecommendationMetadata.fetch_batch(tmdb_service, items, content_type, user_settings=None)
        except Exception as e:
            logger.warning(f"Failed to fetch trending items: {e}")
            return []

    async def _get_recommendations(
        self,
        catalog_id: str,
        content_type: str,
        services: dict[str, Any],
        profile: TasteProfile | None,
        watched_tmdb: set[int],
        watched_imdb: set[str],
        library_items: LibraryCollection,
        limit: int,
        user_settings: UserSettings | None = None,
    ) -> list[dict[str, Any]]:
        """Route to appropriate recommendation service based on catalog ID."""
        if any(catalog_id.startswith(p) for p in ("watchly.loved.", "watchly.watched.")):
            item_id = re.sub(r"^watchly\.(loved|watched)\.", "", catalog_id)
            item_service: ItemBasedService = services["item"]

            recommendations = await item_service.get_recommendations_for_item(
                item_id=item_id,
                content_type=content_type,
                watched_tmdb=watched_tmdb,
                watched_imdb=watched_imdb,
                limit=limit,
            )
            logger.info(f"Found {len(recommendations)} recommendations for item {item_id}")

        elif catalog_id.startswith("watchly.theme."):
            theme_service: ThemeBasedService = services["theme"]

            recommendations = await theme_service.get_recommendations_for_theme(
                theme_id=catalog_id,
                content_type=content_type,
                profile=profile,
                watched_tmdb=watched_tmdb,
                watched_imdb=watched_imdb,
                limit=limit,
            )
            logger.info(f"Found {len(recommendations)} recommendations for theme {catalog_id}")

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
                logger.info(f"No profile for creators, showing trending {content_type}")
                recommendations = await self._get_trending_fallback(content_type, limit, user_settings)
            logger.info(f"Found {len(recommendations)} recommendations from creators")

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
                logger.info(f"No profile for top picks, showing trending {content_type}")
                recommendations = await self._get_trending_fallback(content_type, limit, user_settings)
            logger.info(f"Found {len(recommendations)} top picks for {content_type}")

        elif catalog_id in ("watchly.all.loved", "watchly.liked.all"):
            item_type = "loved" if catalog_id == "watchly.all.loved" else "liked"
            all_based_service: AllBasedService = services["all_based"]
            recommendations = await all_based_service.get_recommendations_from_all_items(
                library_items=library_items,
                content_type=content_type,
                watched_tmdb=watched_tmdb,
                watched_imdb=watched_imdb,
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
