import asyncio
from typing import Any

from loguru import logger

from app.core.settings import UserSettings
from app.models.library import LibraryCollection
from app.models.profile import TasteProfile
from app.services.profile.scorer import ProfileScorer
from app.services.recommendation.filtering import (
    RecommendationFiltering,
    filter_by_genres,
    filter_items_by_settings,
    filter_watched_by_imdb,
)
from app.services.recommendation.metadata import RecommendationMetadata
from app.services.recommendation.scoring import RecommendationScoring
from app.services.recommendation.utils import content_type_to_mtype, resolve_tmdb_id
from app.services.simkl import simkl_service
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
        library_items: LibraryCollection,
        content_type: str,
        watched_tmdb: set[int],
        watched_imdb: set[str],
        limit: int = 20,
        item_type: str = "loved",
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
            limit: Number of items to return
            item_type: "loved" or "liked"
            profile: Optional profile for scoring (if None, uses popularity only)

        Returns:
            List of recommended items
        """
        items = getattr(library_items, item_type, [])

        typed_items = [it for it in items if it.type == content_type]

        logger.info(f"Typed items: {len(typed_items)}")

        if not typed_items or len(typed_items) == 0:
            return []

        # We'll process them in parallel
        top_items = typed_items[:TOP_ITEMS_LIMIT]

        mtype = content_type_to_mtype(content_type)

        # Fetch recommendations
        all_candidates = {}

        simkl_candidates = []
        tmdb_candidates = []

        # Use Simkl if API key available, otherwise fall back to TMDB
        simkl_api_key = self.user_settings.simkl_api_key if self.user_settings else None
        if simkl_api_key:
            simkl_candidates = await self._fetch_simkl_candidates(top_items, mtype)
            if simkl_candidates:
                for candidate in simkl_candidates:
                    candidate_id = candidate.get("id")
                    if candidate_id:
                        all_candidates[candidate_id] = candidate
                logger.info(f"Fetched {len(all_candidates)} candidates from Simkl")
                # filter simkl candidates
                simkl_candidates = list(all_candidates.values())
                simkl_candidates = filter_items_by_settings(simkl_candidates, self.user_settings, simkl=True)
                logger.info(f"Total {len(simkl_candidates)} after filtering")
            else:
                logger.info("Simkl returned no results, falling back to TMDB")

        # Fall back to TMDB if no Simkl key or Simkl returned nothing
        if not simkl_candidates:
            all_candidates = {}
            tasks = []
            logger.info(f"Fetching TMDB recommendations for {len(top_items)} top items")

            for item in top_items:
                item_id = item.id
                if not item_id:
                    continue
                tasks.append(self._fetch_recommendations_for_item(item_id, mtype))

            results = await asyncio.gather(*tasks, return_exceptions=True)

            for res in results:
                if isinstance(res, Exception):
                    logger.debug(f"Error fetching recommendations: {res}")
                    continue
                for candidate in res:
                    candidate_id = candidate.get("id")
                    if candidate_id:
                        all_candidates[candidate_id] = candidate

            logger.info(f"Fetched {len(all_candidates)} candidates from TMDB")

            # Convert to list
            tmdb_candidates = list(all_candidates.values())

            # Apply global settings filter (years, popularity)
            tmdb_candidates = filter_items_by_settings(tmdb_candidates, self.user_settings)

        candidates = simkl_candidates + tmdb_candidates

        # Filter by genres and watched items
        excluded_ids = RecommendationFiltering.get_excluded_genre_ids(self.user_settings, content_type)
        filtered = filter_by_genres(candidates, watched_tmdb, excluded_ids)

        logger.info(f"Filtered {len(filtered)} candidates")

        # Score with profile if available
        scored = []
        if profile:
            for item in filtered:
                try:
                    final_score = RecommendationScoring.calculate_final_score(
                        item=item,
                        profile=profile,
                        scorer=self.scorer,
                        mtype=mtype,
                    )

                    scored.append((final_score, item))
                except Exception as e:
                    logger.debug(f"Failed to score item {item.get('id')}: {e}")
                    continue

            # Sort by score
            scored.sort(key=lambda x: x[0], reverse=True)
            filtered = [item for _, item in scored]
        else:
            # No profile - just use filtered items sorted by popularity/rating
            logger.info("No profile available, sorting by popularity")
            filtered = sorted(filtered, key=lambda x: x.get("popularity", 0) * x.get("vote_average", 0), reverse=True)

        logger.info(f"Scored {len(scored) if scored else len(filtered)} candidates")

        # Enrich metadata
        enriched = await RecommendationMetadata.fetch_batch(
            self.tmdb_service, filtered, content_type, user_settings=self.user_settings
        )

        logger.info(f"Enriched {len(enriched)} items")

        # Final filter (remove watched by IMDB ID)
        final = filter_watched_by_imdb(enriched, watched_imdb)

        # Return top N
        return final

    async def _fetch_simkl_candidates(self, top_items: list[dict[str, Any]], mtype: str) -> list[dict[str, Any]]:
        """
        Fetch recommendations from Simkl for loved/liked items.

        Args:
            top_items: List of library items
            mtype: Media type (movie/tv)

        Returns:
            List of normalized Simkl candidates
        """
        simkl_api_key = self.user_settings.simkl_api_key if self.user_settings else None
        if not simkl_api_key:
            return []

        # Extract IMDB IDs
        imdb_ids = []
        for item in top_items:
            item_id = item.id
            if item_id and item_id.startswith("tt"):
                imdb_ids.append(item_id)

        if not imdb_ids:
            logger.warning("No valid IMDB IDs found for Simkl recommendations")
            return []

        # Get year range for early filtering
        year_min = getattr(self.user_settings, "year_min", None)
        year_max = getattr(self.user_settings, "year_max", None)

        try:
            return await simkl_service.get_recommendations_batch(
                imdb_ids,
                mtype,
                simkl_api_key,
                max_per_item=8,
                year_min=year_min,
                year_max=year_max,
            )
        except Exception as e:
            logger.error(f"Error fetching Simkl recommendations: {e}")
            return []

    async def _fetch_recommendations_for_item(self, item_id: str, mtype: str) -> list[dict[str, Any]]:
        """
        Fetch recommendations for a single item from TMDB.

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
