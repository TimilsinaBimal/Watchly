import asyncio
from typing import Any

from loguru import logger

from app.core.settings import UserSettings
from app.models.taste_profile import TasteProfile
from app.services.profile.scorer import ProfileScorer
from app.services.recommendation.filtering import RecommendationFiltering
from app.services.recommendation.metadata import RecommendationMetadata
from app.services.recommendation.scoring import RecommendationScoring
from app.services.recommendation.utils import (
    content_type_to_mtype,
    filter_by_genres,
    filter_watched_by_imdb,
    resolve_tmdb_id,
)
from app.services.tmdb.service import TMDBService

TOP_ITEMS_LIMIT = 10


class AllBasedService:
    """
    Handles recommendations based on all loved or all liked items.
    """

    def __init__(self, tmdb_service: TMDBService, user_settings: UserSettings | None = None):
        self.tmdb_service = tmdb_service
        self.user_settings = user_settings
        self.scorer = ProfileScorer()

    async def get_recommendations_from_all_items(
        self,
        library_items: dict[str, list[dict[str, Any]]],
        content_type: str,
        watched_tmdb: set[int],
        watched_imdb: set[str],
        whitelist: set[int] | None = None,
        limit: int = 20,
        item_type: str = "loved",  # "loved" or "liked"
        profile: TasteProfile | None = None,
    ) -> list[dict[str, Any]]:
        """
        Get recommendations based on all loved or liked items.

        Strategy:
        1. Get all loved/liked items for the content type
        2. Fetch recommendations for each item (limit to top 10 items to avoid too many API calls)
        3. Combine and deduplicate recommendations
        4. Filter by genres and watched items
        5. Return top N

        Args:
            library_items: Library items dict
            content_type: Content type (movie/series)
            watched_tmdb: Set of watched TMDB IDs
            watched_imdb: Set of watched IMDB IDs
            whitelist: Genre whitelist
            limit: Number of items to return
            item_type: "loved" or "liked"
            profile: Optional profile for scoring (if None, uses popularity only)

        Returns:
            List of recommended items
        """
        # Get all loved or liked items for the content type
        items = library_items.get(item_type, [])
        typed_items = [it for it in items if it.get("type") == content_type]

        if not typed_items or len(typed_items) == 0:
            return []

        # We'll process them in parallel
        top_items = typed_items[:TOP_ITEMS_LIMIT]

        mtype = content_type_to_mtype(content_type)

        # Fetch recommendations for each item in parallel
        all_candidates = {}
        tasks = []

        for item in top_items:
            item_id = item.get("_id", "")
            if not item_id:
                continue

            # Resolve TMDB ID and fetch recommendations
            tasks.append(self._fetch_recommendations_for_item(item_id, mtype))

        # Execute all in parallel
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Combine all recommendations (deduplicate by TMDB ID)
        for res in results:
            if isinstance(res, Exception):
                logger.debug(f"Error fetching recommendations: {res}")
                continue
            for candidate in res:
                candidate_id = candidate.get("id")
                if candidate_id:
                    all_candidates[candidate_id] = candidate

        # Convert to list
        candidates = list(all_candidates.values())

        # Filter by genres and watched items
        excluded_ids = RecommendationFiltering.get_excluded_genre_ids(self.user_settings, content_type)
        whitelist = whitelist or set()
        filtered = filter_by_genres(candidates, watched_tmdb, whitelist, excluded_ids)

        # Score with profile if available
        if profile:
            scored = []
            for item in filtered:
                try:
                    final_score = RecommendationScoring.calculate_final_score(
                        item=item,
                        profile=profile,
                        scorer=self.scorer,
                        mtype=mtype,
                        is_ranked=False,
                        is_fresh=False,
                    )

                    # Apply genre multiplier (if whitelist available)
                    genre_mult = RecommendationFiltering.get_genre_multiplier(item.get("genre_ids"), whitelist)
                    final_score *= genre_mult

                    scored.append((final_score, item))
                except Exception as e:
                    logger.debug(f"Failed to score item {item.get('id')}: {e}")
                    continue

            # Sort by score
            scored.sort(key=lambda x: x[0], reverse=True)
            filtered = [item for _, item in scored]

        # Enrich metadata
        enriched = await RecommendationMetadata.fetch_batch(
            self.tmdb_service, filtered, content_type, user_settings=self.user_settings
        )

        # Final filter (remove watched by IMDB ID)
        final = filter_watched_by_imdb(enriched, watched_imdb)

        # Return top N
        return final

    async def _fetch_recommendations_for_item(self, item_id: str, mtype: str) -> list[dict[str, Any]]:
        """
        Fetch recommendations for a single item.

        Args:
            item_id: Item ID (tt... or tmdb:...)
            mtype: Media type (movie/tv)

        Returns:
            List of candidate items
        """
        # Resolve TMDB ID
        tmdb_id = await resolve_tmdb_id(item_id, self.tmdb_service)
        if not tmdb_id:
            return []

        combined = {}

        # Fetch 1 page each for recommendations
        try:
            res = await self.tmdb_service.get_recommendations(tmdb_id, mtype, page=1)
            for item in res.get("results", []):
                candidate_id = item.get("id")
                if candidate_id:
                    combined[candidate_id] = item
        except Exception as e:
            logger.debug(f"Error fetching recommendations for {tmdb_id}: {e}")

        return list(combined.values())
