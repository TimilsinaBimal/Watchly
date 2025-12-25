import asyncio
from typing import Any

from fastapi import HTTPException
from loguru import logger

from app.core.settings import UserSettings
from app.models.taste_profile import TasteProfile
from app.services.recommendation.filtering import RecommendationFiltering
from app.services.recommendation.metadata import RecommendationMetadata
from app.services.recommendation.utils import content_type_to_mtype, filter_watched_by_imdb
from app.services.tmdb.service import TMDBService


class CreatorsService:
    """
    Handles recommendations from favorite creators (directors and cast).

    Strategy:
    1. Build profile from smart-sampled library items
    2. Get top directors and cast from profile
    3. Count raw frequencies to filter single-appearance creators
    4. Prioritize creators with 2+ appearances, fill with single if needed
    5. Fetch recommendations from each creator (fewer pages for single-appearance)
    6. Filter and return results
    """

    def __init__(self, tmdb_service: TMDBService, user_settings: UserSettings | None = None):
        self.tmdb_service: TMDBService = tmdb_service
        self.user_settings: UserSettings | None = user_settings

    async def get_recommendations_from_creators(
        self,
        profile: TasteProfile,
        content_type: str,
        watched_tmdb: set[int],
        watched_imdb: set[str],
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """
        Get recommendations from user's top favorite directors and cast.

        Args:
            profile: User taste profile
            content_type: Content type (movie/series)
            watched_tmdb: Set of watched TMDB IDs
            watched_imdb: Set of watched IMDB IDs
            limit: Number of recommendations to return

        Returns:
            List of recommended items
        """
        mtype = content_type_to_mtype(content_type)

        # Get top 5 directors and cast directly from profile
        selected_directors = profile.get_top_directors(limit=5)
        selected_cast = profile.get_top_cast(limit=5)

        if not selected_directors and not selected_cast:
            raise HTTPException(status_code=404, detail="No top directors or cast found")

        # Fetch recommendations from creators
        all_candidates = {}
        tasks = []

        # Create tasks for directors (fetch 2 pages each)
        for dir_id, _ in selected_directors:
            for page in [1, 2]:
                # TV uses with_people, movies use with_crew
                if mtype == "tv":
                    discover_params = {"with_people": str(dir_id), "page": page}
                else:
                    discover_params = {"with_crew": str(dir_id), "page": page}

                tasks.append(self._fetch_discover_page(mtype, discover_params, dir_id, "director"))

        # Create tasks for cast (fetch 2 pages each)
        for cast_id, _ in selected_cast:
            for page in [1, 2]:
                discover_params = {"with_cast": str(cast_id), "page": page}
                tasks.append(self._fetch_discover_page(mtype, discover_params, cast_id, "cast"))

        # Execute all tasks in parallel
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Collect results
        for result in results:
            if isinstance(result, Exception):
                continue
            for item in result:
                item_id = item.get("id")
                if item_id:
                    all_candidates[item_id] = item

        # Filter candidates
        excluded_ids = RecommendationFiltering.get_excluded_genre_ids(self.user_settings, content_type)
        filtered = []

        for item in all_candidates.values():
            item_id = item.get("id")
            if not item_id or item_id in watched_tmdb:
                continue

            # Genre whitelist check
            genre_ids = item.get("genre_ids", [])

            # Excluded genres check
            if excluded_ids and any(gid in excluded_ids for gid in genre_ids):
                continue

            filtered.append(item)

        # Enrich metadata
        enriched = await RecommendationMetadata.fetch_batch(
            self.tmdb_service, filtered, content_type, user_settings=self.user_settings
        )

        # Final filter (remove watched by IMDB ID)
        final = filter_watched_by_imdb(enriched, watched_imdb)

        return final[:limit]

    async def _fetch_discover_page(
        self, mtype: str, discover_params: dict[str, Any], creator_id: int, creator_type: str
    ) -> list[dict[str, Any]]:
        try:
            results = await self.tmdb_service.get_discover(mtype, **discover_params)
            return results.get("results", [])
        except Exception as e:
            logger.debug(f"Error fetching recommendations for {creator_type} {creator_id}: {e}")
            return []
