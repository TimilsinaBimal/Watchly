import asyncio
from typing import Any

from loguru import logger

from app.services.recommendation.filtering import RecommendationFiltering
from app.services.recommendation.metadata import RecommendationMetadata
from app.services.recommendation.utils import (
    content_type_to_mtype,
    filter_by_genres,
    filter_watched_by_imdb,
    resolve_tmdb_id,
)


class ItemBasedService:
    """
    Handles item-based recommendations (Because you watched/loved).
    """

    def __init__(self, tmdb_service: Any, user_settings: Any = None):
        self.tmdb_service = tmdb_service
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
        candidates = await self._fetch_candidates(tmdb_id, mtype)

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

        # Fetch 2 pages each for recommendations and similar
        for action in ["recommendations", "similar"]:
            method = getattr(self.tmdb_service, f"get_{action}")
            results = await asyncio.gather(*[method(tmdb_id, mtype, page=p) for p in [1, 2]], return_exceptions=True)

            for res in results:
                if isinstance(res, Exception):
                    logger.debug(f"Error fetching {action} for {tmdb_id}: {res}")
                    continue
                for item in res.get("results", []):
                    item_id = item.get("id")
                    if item_id:
                        combined[item_id] = item

        return list(combined.values())
