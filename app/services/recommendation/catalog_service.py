import asyncio
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
from app.services.redis_service import redis_service
from app.services.tmdb.service import get_tmdb_service
from app.services.token_store import token_store
from app.services.user_cache import user_cache
from app.services.warmup import warmup_service

REFRESH_LOCK_PREFIX = "watchly:refreshlock:"
# Long enough to cover a slow rebuild, short enough that a worker killed mid-refresh
# doesn't keep a row stale for long.
REFRESH_LOCK_TTL_SECONDS = 600


class CatalogService:
    def __init__(self) -> None:
        # Retained so a background refresh isn't garbage collected mid-flight.
        self._refresh_tasks: set[asyncio.Task] = set()

    async def get_catalog(
        self, token: str, content_type: str, catalog_id: str
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Get catalog recommendations."""
        self._validate_inputs(token, content_type, catalog_id)

        # Resolve merge aliases up front so credential reads and cache keys all
        # use the surviving account token.
        token = await token_store.resolve_alias(token)

        headers = self._headers()

        logger.debug(f"[{redact_token(token)}] Fetching catalog for {content_type} with id {catalog_id}")

        # Load credentials (needed for cache check + shuffle settings)
        credentials = await token_store.get_user_data(token)
        if not credentials:
            logger.error("No credentials found for token")
            raise HTTPException(
                status_code=401,
                detail="Invalid or expired token. Please reconfigure the addon.",
            )

        # Trigger lazy update if needed. Skipped while a warm-up is running: on a
        # re-configure last_updated carries over from the old record, so this would
        # otherwise fire a full manifest rebuild and Stremio push alongside the warm
        # that is already doing exactly that.
        if settings.AUTO_UPDATE_CATALOGS and not await warmup_service.is_warming(token):
            try:
                await catalog_updater.trigger_update(token, credentials)
            except Exception as e:
                logger.error(f"[{redact_token(token)}] Failed to trigger auto update: {e}")

        # Check cache first — avoids auth/library/profile loading on cache hit
        cached_result = await user_cache.get_catalog(token, content_type, catalog_id)

        if cached_result:
            data, created_at = cached_result
            age = int(time.time()) - created_at
            user_settings = extract_settings(credentials)
            data["metas"] = shuffle_data_if_needed(user_settings, catalog_id, data["metas"])

            if age < settings.CATALOG_REFRESH_INTERVAL_SECONDS:
                logger.debug(f"[{redact_token(token)}] Using cached catalog for {content_type}/{catalog_id}")
                return data, headers

            # Stale but serveable: hand it back now and rebuild behind the response.
            # Rebuilding inline meant every row on a home screen stalled for a full
            # rebuild once the cache aged out, which is most of the wait users saw.
            logger.info(
                f"[{redact_token(token)}] Catalog stale (age: {age}s) for {content_type}/{catalog_id}, "
                "serving stale and refreshing in the background"
            )
            self._enqueue_refresh(token, content_type, catalog_id)
            return data, headers

        logger.info(
            f"[{redact_token(token)}] Catalog not cached for {content_type}/{catalog_id}, building from scratch"
        )

        # Nothing cached to serve, so this one has to build on the request.
        ctx = await load_user_context(token)
        try:
            return await self._build_catalog(ctx, content_type, catalog_id, headers)
        finally:
            await ctx.close()

    @staticmethod
    def _headers() -> dict[str, Any]:
        """Response headers.

        One max-age for fresh and stale bodies alike. A fresh body used to be
        cacheable 720x longer, which made sense only while ids churned and acted as
        accidental cache-busters; with stable slot ids this header is what tells a
        client a row has changed.
        """
        max_age = settings.CATALOG_CACHE_TTL
        return {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "*",
            "Content-Type": "application/json",
            "Cache-Control": f"private, max-age={max_age},stale-while-revalidate=3600, stale-if-error=1800",
        }

    def _enqueue_refresh(self, token: str, content_type: str, catalog_id: str) -> None:
        task = asyncio.create_task(self._refresh_in_background(token, content_type, catalog_id))
        self._refresh_tasks.add(task)
        task.add_done_callback(self._refresh_tasks.discard)

    async def _refresh_in_background(self, token: str, content_type: str, catalog_id: str) -> None:
        """Rebuild a stale catalog into the cache.

        Locked in Redis rather than in-process because Stremio asks for every
        enabled row at once: without it, one home screen open would kick off a full
        rebuild per row.
        """
        lock_key = f"{REFRESH_LOCK_PREFIX}{token}:{content_type}:{catalog_id}"
        if not await redis_service.set_nx(lock_key, "1", REFRESH_LOCK_TTL_SECONDS):
            logger.debug(f"[{redact_token(token)}] Refresh already running for {content_type}/{catalog_id}")
            return

        try:
            ctx = await load_user_context(token)
            try:
                # Called for the cache write it performs; the response is discarded.
                await self._build_catalog(ctx, content_type, catalog_id, self._headers())
            finally:
                await ctx.close()
            logger.info(f"[{redact_token(token)}] Background refresh done for {content_type}/{catalog_id}")
        except Exception as e:
            logger.warning(f"[{redact_token(token)}] Background refresh failed for {content_type}/{catalog_id}: {e}")
        finally:
            await redis_service.delete(lock_key)

    async def _build_catalog(
        self,
        ctx: UserContext,
        content_type: str,
        catalog_id: str,
        headers: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Build fresh catalog content using the loaded user context."""
        try:
            # Resolved only for building. The cache key stays the slot id the client
            # asked for, which is the whole point: it survives a definition change.
            resolved_id = await self._resolve_slot(ctx.token, content_type, catalog_id)
            if resolved_id is None:
                return {"metas": []}, headers

            services = self._initialize_services(ctx.user_settings)
            profile_service: ProfileService = services["profile"]

            # Load profile (cached or build fresh)
            cached_data = await user_cache.get_profile_and_watched_sets(ctx.token, content_type)

            requested_source = ctx.user_settings.watch_history_source if ctx.user_settings else "stremio"
            cached_source = getattr(cached_data[0], "source", "stremio") if cached_data and cached_data[0] else None
            if cached_data and cached_source is not None and cached_source != requested_source:
                logger.info(
                    f"[{redact_token(ctx.token)}] Cached profile source '{cached_source}' "
                    f"!= requested '{requested_source}'; rebuilding."
                )
                cached_data = None

            if cached_data:
                profile, watched_tmdb, watched_imdb = cached_data
                logger.debug(f"[{redact_token(ctx.token)}] Using cached profile for {content_type}")
            else:
                source = ctx.user_settings.watch_history_source if ctx.user_settings else "stremio"
                logger.info(
                    f"[{redact_token(ctx.token)}] Profile not cached for {content_type}, building from {source}"
                )
                profile, watched_tmdb, watched_imdb = await profile_service.build_and_cache_profile(
                    ctx.token,
                    content_type,
                    ctx.library,
                    ctx.bundle,
                    ctx.auth_key,
                    user_settings=ctx.user_settings,
                )

            recommendations = await self._get_recommendations(
                catalog_id=resolved_id,
                content_type=content_type,
                services=services,
                profile=profile,
                watched_tmdb=watched_tmdb,
                watched_imdb=watched_imdb,
                library_items=ctx.library,
                limit=DEFAULT_CATALOG_LIMIT,
                user_settings=ctx.user_settings,
            )

            logger.debug(f"Returning {len(recommendations)} items for {content_type}")

            cleaned = [m for m in (clean_meta(m) for m in recommendations) if m is not None]
            cleaned = shuffle_data_if_needed(ctx.user_settings, catalog_id, cleaned)

            data = {"metas": cleaned}
            if cleaned:
                await user_cache.set_catalog(ctx.token, content_type, catalog_id, data, settings.CATALOG_STALE_TTL)

            return data, headers

        except Exception as e:
            logger.error(f"[{redact_token(ctx.token)}] Failed to generate catalog: {e}")

            # A stale copy, when one exists, is served before this is ever reached.
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
        # watchly.loved.* / watchly.watched.* kept for legacy stored manifests
        # — installed Stremio clients may still request these IDs after the
        # loved/watched merge until the manifest refreshes.
        supported_prefixes = (
            "watchly.theme.",
            "watchly.item.",
            "watchly.loved.",
            "watchly.watched.",
        )
        if catalog_id not in supported_base and not any(catalog_id.startswith(p) for p in supported_prefixes):
            logger.warning(f"Invalid id: {catalog_id}")
            raise HTTPException(
                status_code=400,
                detail=(
                    "Invalid id. Supported: 'watchly.rec', 'watchly.creators', "
                    "'watchly.theme.<params>', 'watchly.item.<imdb>', "
                    "'watchly.all.loved', 'watchly.liked.all'"
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

    @staticmethod
    async def _resolve_slot(token: str, content_type: str, catalog_id: str) -> str | None:
        """Expand a slot id into the row definition it currently points at.

        Served ids are stable slots (`watchly.theme.2`) so the cache key never moves
        when the row's definition changes. The definitions live in the slot map, and
        expanding one back into the old self-describing form means the existing
        parsers are untouched.

        Ids that aren't slots are returned unchanged: manifests installed before this
        carry self-describing ids and Stremio keeps requesting them until it refreshes.

        None means the slot has no definition — the user reduced their row count and
        the installed client still asks for the dropped slot. Passing the id through
        instead would hand the item engine a bare "3", which it reads as TMDB id 3.
        """
        match = re.match(r"^watchly\.(theme|item)\.(\d+)$", catalog_id)
        if not match:
            return catalog_id

        prefix, slot = match.groups()
        definition = (await user_cache.get_row_map(token, content_type)).get(f"{prefix}.{slot}")
        if not definition:
            logger.warning(f"[{redact_token(token)}] No row definition for {catalog_id} ({content_type})")
            return None

        return f"watchly.{prefix}.{definition}"

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
        if any(catalog_id.startswith(p) for p in ("watchly.item.", "watchly.loved.", "watchly.watched.")):
            item_id = re.sub(r"^watchly\.(item|loved|watched)\.", "", catalog_id)
            item_service: ItemBasedService = services["item"]

            recommendations = await item_service.get_recommendations_for_item(
                item_id=item_id,
                content_type=content_type,
                watched_tmdb=watched_tmdb,
                watched_imdb=watched_imdb,
                limit=limit,
            )
            logger.debug(f"Found {len(recommendations)} recommendations for item {item_id}")

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
            logger.debug(f"Found {len(recommendations)} recommendations for theme {catalog_id}")

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
            logger.debug(f"Found {len(recommendations)} recommendations from creators")

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
            logger.debug(f"Found {len(recommendations)} top picks for {content_type}")

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
