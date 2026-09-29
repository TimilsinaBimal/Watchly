import asyncio
from typing import Any

from loguru import logger

from app.core.settings import UserSettings
from app.services.recommendation.filtering import (
    RecommendationFiltering,
    filter_by_genres,
    filter_items_by_settings,
    filter_watched_by_imdb,
)
from app.services.recommendation.metadata import RecommendationMetadata
from app.services.recommendation.utils import content_type_to_mtype, resolve_tmdb_id
from app.services.simkl import simkl_service
from app.services.tmdb.service import TMDBService


class ItemBasedService:
    """Handles item-based recommendations (Because you watched/loved)."""

    def __init__(self, tmdb_service: TMDBService, user_settings: UserSettings):
        self.tmdb_service = tmdb_service
        self.user_settings = user_settings

    async def get_recommendations_for_item(
        self,
        item_id: str,
        content_type: str,
        watched_tmdb: set[int],
        watched_imdb: set[str],
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        tmdb_id = await resolve_tmdb_id(item_id, self.tmdb_service)
        if not tmdb_id:
            return []

        # The seed itself must not come back as its own recommendation.
        watched_tmdb = watched_tmdb | {tmdb_id}

        mtype = content_type_to_mtype(content_type)

        tasks = [self._fetch_candidates_from_simkl(item_id, mtype), self._fetch_candidates(tmdb_id, mtype)]
        simkl_result, tmdb_result = await asyncio.gather(*tasks, return_exceptions=True)
        if isinstance(simkl_result, Exception):
            logger.warning(f"item-based simkl candidate fetch failed for {item_id}: {type(simkl_result).__name__}")
            simkl_candidates: list = []
        else:
            simkl_candidates = simkl_result
        if isinstance(tmdb_result, Exception):
            logger.warning(f"item-based tmdb candidate fetch failed for {item_id}: {type(tmdb_result).__name__}")
            candidates: list = []
        else:
            candidates = tmdb_result

        candidates = filter_items_by_settings(candidates, self.user_settings)
        candidates = simkl_candidates + candidates

        excluded_ids = RecommendationFiltering.get_excluded_genre_ids(self.user_settings, content_type)
        filtered = filter_by_genres(candidates, watched_tmdb, excluded_ids)

        enriched = await RecommendationMetadata.fetch_batch(
            self.tmdb_service, filtered, content_type, user_settings=self.user_settings
        )
        return filter_watched_by_imdb(enriched, watched_imdb)

    async def _fetch_candidates_from_simkl(self, imdb_id: str, mtype: str):
        simkl_api_key = self.user_settings.simkl_api_key
        if not simkl_api_key:
            logger.debug("Simkl API key not found. Using TMDB for recommendations")
            return []
        return await simkl_service.get_recommendations(imdb_id, mtype, simkl_api_key)

    async def _fetch_candidates(self, tmdb_id: int, mtype: str) -> list[dict[str, Any]]:
        combined = {}

        async def fetch_and_combine(fetch_method, source_name, pages: tuple[int, ...] = (1, 2, 3)):
            results = await asyncio.gather(
                *[fetch_method(tmdb_id, mtype, page=p) for p in pages],
                return_exceptions=True,
            )
            for res in results:
                if isinstance(res, Exception):
                    logger.warning(f"Error fetching {source_name} for {tmdb_id}: {type(res).__name__}")
                    continue
                for item in res.get("results", []):
                    item_id = item.get("id")
                    if item_id:
                        combined[item_id] = item

        await fetch_and_combine(self.tmdb_service.get_recommendations, "recommendations")

        if len(combined) < 30:
            await fetch_and_combine(self.tmdb_service.get_similar, "similar")

        # If the post-settings filter produces fewer than 30 candidates, pull
        # more pages of similar before returning so the caller has headroom.
        if len(filter_items_by_settings(combined.values(), self.user_settings)) < 30:
            await fetch_and_combine(self.tmdb_service.get_similar, "similar", pages=(4, 5, 6))

        # Caller re-applies filter_items_by_settings, so return the merged set.
        return list(combined.values())
