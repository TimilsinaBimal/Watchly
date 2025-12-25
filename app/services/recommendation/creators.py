"""
Creators-Based Recommendations Service.

Fetches recommendations from user's favorite directors and cast members.
Uses frequency filtering to avoid single-appearance creators dominating.
"""

import asyncio
from collections import defaultdict
from typing import Any

from loguru import logger

from app.models.taste_profile import TasteProfile
from app.services.recommendation.filtering import RecommendationFiltering
from app.services.recommendation.metadata import RecommendationMetadata
from app.services.recommendation.utils import content_type_to_mtype, filter_watched_by_imdb, resolve_tmdb_id


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

    def __init__(self, tmdb_service: Any, user_settings: Any = None):
        """
        Initialize creators service.

        Args:
            tmdb_service: TMDB service for API calls
            user_settings: User settings for exclusions
        """
        self.tmdb_service = tmdb_service
        self.user_settings = user_settings

    async def get_recommendations_from_creators(
        self,
        profile: TasteProfile,
        content_type: str,
        library_items: dict[str, list[dict[str, Any]]],
        watched_tmdb: set[int],
        watched_imdb: set[str],
        whitelist: set[int],
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """
        Get recommendations from user's top favorite directors and cast.

        Args:
            profile: User taste profile
            content_type: Content type (movie/series)
            library_items: Library items dict (for frequency counting)
            watched_tmdb: Set of watched TMDB IDs
            watched_imdb: Set of watched IMDB IDs
            whitelist: Genre whitelist
            limit: Number of recommendations to return

        Returns:
            List of recommended items
        """
        mtype = content_type_to_mtype(content_type)

        # Get top directors and cast from profile
        top_directors = profile.get_top_directors(limit=20)
        top_cast = profile.get_top_cast(limit=20)

        if not top_directors and not top_cast:
            return []

        # Count raw frequencies to filter single-appearance creators
        director_frequencies, cast_frequencies = await self._count_creator_frequencies(library_items, content_type)

        # Separate creators by frequency
        MIN_FREQUENCY = 2
        reliable_directors = [
            (dir_id, score) for dir_id, score in top_directors if director_frequencies.get(dir_id, 0) >= MIN_FREQUENCY
        ]
        single_directors = [
            (dir_id, score) for dir_id, score in top_directors if director_frequencies.get(dir_id, 0) == 1
        ]

        reliable_cast = [
            (cast_id, score) for cast_id, score in top_cast if cast_frequencies.get(cast_id, 0) >= MIN_FREQUENCY
        ]
        single_cast = [(cast_id, score) for cast_id, score in top_cast if cast_frequencies.get(cast_id, 0) == 1]

        # Select top 5: prioritize reliable (2+), fill with single if needed
        selected_directors = reliable_directors[:5]
        remaining_director_slots = 5 - len(selected_directors)
        if remaining_director_slots > 0:
            selected_directors.extend(single_directors[:remaining_director_slots])

        selected_cast = reliable_cast[:5]
        remaining_cast_slots = 5 - len(selected_cast)
        if remaining_cast_slots > 0:
            selected_cast.extend(single_cast[:remaining_cast_slots])

        if not selected_directors and not selected_cast:
            return []

        # Fetch recommendations from creators
        all_candidates = {}

        # Fetch from directors
        for dir_id, _ in selected_directors:
            is_reliable = director_frequencies.get(dir_id, 0) >= MIN_FREQUENCY
            pages_to_fetch = [1, 2, 3] if is_reliable else [1]  # Fewer pages for single-appearance

            try:
                for page in pages_to_fetch:
                    # TV uses with_people, movies use with_crew
                    if mtype == "tv":
                        discover_params = {"with_people": str(dir_id), "page": page}
                    else:
                        discover_params = {"with_crew": str(dir_id), "page": page}

                    results = await self.tmdb_service.get_discover(mtype, **discover_params)
                    for item in results.get("results", []):
                        item_id = item.get("id")
                        if item_id:
                            all_candidates[item_id] = item
            except Exception as e:
                logger.debug(f"Error fetching recommendations for director {dir_id}: {e}")

        # Fetch from cast
        for cast_id, _ in selected_cast:
            is_reliable = cast_frequencies.get(cast_id, 0) >= MIN_FREQUENCY
            pages_to_fetch = [1, 2, 3] if is_reliable else [1]  # Fewer pages for single-appearance

            try:
                for page in pages_to_fetch:
                    discover_params = {"with_cast": str(cast_id), "page": page}
                    results = await self.tmdb_service.get_discover(mtype, **discover_params)
                    for item in results.get("results", []):
                        item_id = item.get("id")
                        if item_id:
                            all_candidates[item_id] = item
            except Exception as e:
                logger.debug(f"Error fetching recommendations for cast {cast_id}: {e}")

        # Filter candidates
        excluded_ids = RecommendationFiltering.get_excluded_genre_ids(self.user_settings, content_type)
        filtered = []

        for item in all_candidates.values():
            item_id = item.get("id")
            if not item_id or item_id in watched_tmdb:
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
        final = filter_watched_by_imdb(enriched, watched_imdb)

        return final[:limit]

    async def _count_creator_frequencies(
        self, library_items: dict[str, list[dict[str, Any]]], content_type: str
    ) -> tuple[dict[int, int], dict[int, int]]:
        """
        Count raw frequencies of directors and cast in library items.

        Args:
            library_items: Library items dict
            content_type: Content type

        Returns:
            Tuple of (director_frequencies, cast_frequencies)
        """
        director_frequencies = defaultdict(int)
        cast_frequencies = defaultdict(int)

        all_items = (
            library_items.get("loved", [])
            + library_items.get("liked", [])
            + library_items.get("watched", [])
            + library_items.get("added", [])
        )
        typed_items = [it for it in all_items if it.get("type") == content_type]

        async def count_creators(item: dict):
            try:
                # Resolve TMDB ID
                item_id = item.get("_id", "")
                tmdb_id = await resolve_tmdb_id(item_id, self.tmdb_service)

                if not tmdb_id:
                    return

                # Fetch metadata
                if content_type == "movie":
                    meta = await self.tmdb_service.get_movie_details(tmdb_id)
                else:
                    meta = await self.tmdb_service.get_tv_details(tmdb_id)

                if not meta:
                    return

                credits = meta.get("credits") or {}
                crew = credits.get("crew") or []
                cast = credits.get("cast") or []

                # Count directors
                for c in crew:
                    if isinstance(c, dict) and c.get("job") == "Director":
                        dir_id = c.get("id")
                        if dir_id:
                            director_frequencies[dir_id] += 1

                # Count cast (top 5 only)
                for c in cast[:5]:
                    if isinstance(c, dict) and c.get("id"):
                        cast_frequencies[c.get("id")] += 1
            except Exception:
                pass

        # Count frequencies in parallel
        await asyncio.gather(*[count_creators(item) for item in typed_items], return_exceptions=True)

        return director_frequencies, cast_frequencies
