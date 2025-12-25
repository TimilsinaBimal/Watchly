"""
Item-Based Recommendations Service.

Minimal processing: fetch similar/recommendations from TMDB, filter watched/excluded.
No heavy scoring - TMDB recommendations are already good.
"""

import asyncio
from typing import Any

from loguru import logger

from app.services.recommendation.filtering import RecommendationFiltering
from app.services.recommendation.metadata import RecommendationMetadata


class ItemBasedService:
    """
    Handles item-based recommendations (Because you watched/loved).

    Strategy: Minimal processing - just filter and return.
    TMDB recommendations are already curated, no need for heavy scoring.
    """

    def __init__(self, tmdb_service: Any, user_settings: Any = None):
        """
        Initialize item-based service.

        Args:
            tmdb_service: TMDB service for API calls
            user_settings: User settings for exclusions
        """
        self.tmdb_service = tmdb_service
        self.user_settings = user_settings

    async def get_recommendations_for_item(
        self,
        item_id: str,
        content_type: str,
        watched_tmdb: set[int],
        watched_imdb: set[str],
        limit: int = 20,
        integration: Any = None,
        library_items: dict | None = None,
    ) -> list[dict[str, Any]]:
        """
        Get recommendations for a specific item.

        Minimal processing:
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
        tmdb_id = await self._resolve_tmdb_id(item_id)
        if not tmdb_id:
            return []

        # Exclude source item
        watched_tmdb = watched_tmdb.copy()
        watched_tmdb.add(tmdb_id)

        mtype = "tv" if content_type in ("tv", "series") else "movie"

        # Fetch candidates (similar + recommendations, 2 pages each)
        candidates = await self._fetch_candidates(tmdb_id, mtype)

        # Get genre whitelist and excluded genres
        whitelist = await self._get_genre_whitelist(content_type, integration, library_items)
        excluded_ids = RecommendationFiltering.get_excluded_genre_ids(self.user_settings, content_type)

        # Filter candidates
        filtered = []
        for item in candidates:
            item_id_val = item.get("id")
            if not item_id_val or item_id_val in watched_tmdb:
                continue

            # Genre whitelist check
            genre_ids = item.get("genre_ids", [])
            if not RecommendationFiltering.passes_top_genre_whitelist(genre_ids, whitelist):
                continue

            # Excluded genres check
            if excluded_ids and any(gid in excluded_ids for gid in genre_ids):
                continue

            filtered.append(item)

        # Enrich metadata
        enriched = await RecommendationMetadata.fetch_batch(
            self.tmdb_service, filtered, content_type, target_count=limit, user_settings=self.user_settings
        )

        # Final filter (remove watched by IMDB ID)
        final = []
        for item in enriched:
            if item.get("id") in watched_imdb:
                continue
            if item.get("_external_ids", {}).get("imdb_id") in watched_imdb:
                continue
            final.append(item)

        return final[:limit]

    async def _resolve_tmdb_id(self, item_id: str) -> int | None:
        """
        Resolve item ID to TMDB ID.

        Args:
            item_id: Item ID in various formats

        Returns:
            TMDB ID or None
        """
        if item_id.startswith("tmdb:"):
            try:
                return int(item_id.split(":")[1])
            except (ValueError, IndexError):
                return None
        elif item_id.startswith("tt"):
            tmdb_id, _ = await self.tmdb_service.find_by_imdb_id(item_id)
            return tmdb_id
        else:
            try:
                return int(item_id)
            except ValueError:
                return None

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

    async def _get_genre_whitelist(
        self, content_type: str, integration: Any = None, library_items: dict | None = None
    ) -> set[int]:
        """
        Get genre whitelist for content type.

        For item-based recommendations, we use a lenient whitelist approach.
        Since TMDB recommendations are already curated, we don't need strict filtering.
        But we can use profile-based whitelist if provided.

        Args:
            content_type: Content type
            integration: ProfileIntegration instance (optional)
            library_items: Library items dict (optional)

        Returns:
            Set of genre IDs (empty = no filtering)
        """
        if integration and library_items:
            return await integration.get_genre_whitelist(library_items, content_type)
        return set()
