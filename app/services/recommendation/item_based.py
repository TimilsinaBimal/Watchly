import asyncio
from typing import Any

from loguru import logger

from app.services.recommendation.filtering import RecommendationFiltering
from app.services.recommendation.metadata import RecommendationMetadata
from app.services.recommendation.utils import (
    content_type_to_mtype,
    filter_by_genres,
    filter_items_by_settings,
    filter_watched_by_imdb,
    resolve_tmdb_id,
)
from app.services.simkl import simkl_service
from app.services.tmdb.service import TMDBService


class ItemBasedService:
    """
    Handles item-based recommendations (Because you watched/loved).
    """

    def __init__(self, tmdb_service: Any, user_settings: Any = None):
        self.tmdb_service: TMDBService = tmdb_service
        self.user_settings = user_settings

    async def get_recommendations_for_item(
        self,
        item_id: str,
        content_type: str,
        watched_tmdb: set[int] | None = None,
        watched_imdb: set[str] | None = None,
        limit: int = 20,
        whitelist: set[int] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Get recommendations for a specific item.

        Strategy:
        1. Fetch similar + recommendations from TMDB (2 pages each)
        2. Filter watched items
        3. Filter excluded genres
        4. Apply genre whitelist
        5. Return top N

        Args:
            item_id: Item ID (tt... or tmdb:...)
            content_type: Content type (movie/series)
            watched_tmdb: Set of watched TMDB IDs
            watched_imdb: Set of watched IMDB IDs
            limit: Number of items to return

        Returns:
            List of recommended items
        """
        # Resolve TMDB ID
        tmdb_id = await resolve_tmdb_id(item_id, self.tmdb_service)
        if not tmdb_id:
            return []

        # Exclude source item
        watched_tmdb = watched_tmdb.copy() if watched_tmdb else set()
        watched_tmdb.add(tmdb_id)

        mtype = content_type_to_mtype(content_type)

        # Fetch candidates (similar + recommendations, 2 pages each)
        tasks = [self._fetch_candidates_from_simkl(item_id, mtype), self._fetch_candidates(tmdb_id, mtype)]
        simkl_candidates, candidates = await asyncio.gather(*tasks)

        # Apply global settings filter (years, popularity)
        candidates = filter_items_by_settings(candidates, self.user_settings)

        # extend candidates always include simkl candidates
        candidates = simkl_candidates + candidates

        # Filter by genres and watched items
        excluded_ids = RecommendationFiltering.get_excluded_genre_ids(self.user_settings, content_type)
        filtered = filter_by_genres(candidates, watched_tmdb, whitelist, excluded_ids)

        # Enrich metadata
        enriched = await RecommendationMetadata.fetch_batch(
            self.tmdb_service, filtered, content_type, user_settings=self.user_settings
        )

        # Final filter (remove watched by IMDB ID)
        final = filter_watched_by_imdb(enriched, watched_imdb or set())

        return final

    async def _fetch_candidates_from_simkl(self, imdb_id: str, mtype: str):
        # check if user_settings has simkl api key or not
        logger.info("Fetching recommendations from Simkl")
        simkl_api_key = self.user_settings.simkl_api_key
        if not simkl_api_key:
            logger.warning("Simkl API key not found. Using TMDB for recommendations")
            return []
        return await simkl_service.get_recommendations(imdb_id, mtype, simkl_api_key)

    async def _fetch_candidates(self, tmdb_id: int, mtype: str) -> list[dict[str, Any]]:
        """
        Fetch candidates from TMDB (similar + recommendations).

        Args:
            tmdb_id: TMDB ID
            mtype: Media type (movie/tv)

        Returns:
            List of candidate items
        """
        combined = {}

        async def fetch_and_combine(fetch_method, source_name, pages: list[int] = [1, 2, 3]):
            results = await asyncio.gather(
                *[fetch_method(tmdb_id, mtype, page=p) for p in pages],
                return_exceptions=True,
            )
            for res in results:
                if isinstance(res, Exception):
                    logger.warning(f"Error fetching {source_name} for {tmdb_id}: {res}")
                    continue
                for item in res.get("results", []):
                    item_id = item.get("id")
                    if item_id:
                        combined[item_id] = item

        await fetch_and_combine(self.tmdb_service.get_recommendations, "recommendations")

        if not combined or len(combined) < 30:
            await fetch_and_combine(self.tmdb_service.get_similar, "similar")

        # apply filter and check
        filtered = filter_items_by_settings(combined.values(), self.user_settings)

        if not filtered or len(filtered) < 30:
            # fetch more similar items if there are less than 30 items after user_settings filter
            await fetch_and_combine(self.tmdb_service.get_similar, "similar", pages=[4, 5, 6])

        return list(combined.values())
