import asyncio
from typing import Any, Literal

from loguru import logger

from app.core.settings import UserSettings
from app.models.library import LibraryCollection, StremioLibraryItem
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
    """Handles recommendations based on all loved or all liked items."""

    def __init__(self, tmdb_service: TMDBService, user_settings: UserSettings):
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
        item_type: Literal["loved", "liked"] = "loved",
        profile: TasteProfile | None = None,
    ) -> list[dict[str, Any]]:
        """Recommendations seeded by the user's top loved or liked items; scored when a profile exists."""
        items = library_items.loved if item_type == "loved" else library_items.liked
        typed_items = [it for it in items if it.type == content_type]
        logger.debug(f"Typed items: {len(typed_items)}")
        if not typed_items:
            return []

        top_items = typed_items[:TOP_ITEMS_LIMIT]
        mtype = content_type_to_mtype(content_type)

        all_candidates = {}
        simkl_candidates = []
        tmdb_candidates = []

        if self.user_settings.simkl_api_key:
            simkl_candidates = await self._fetch_simkl_candidates(top_items, mtype)
            if simkl_candidates:
                for candidate in simkl_candidates:
                    candidate_id = candidate.get("id")
                    if candidate_id:
                        all_candidates[candidate_id] = candidate
                logger.debug(f"Fetched {len(all_candidates)} candidates from Simkl")
                simkl_candidates = filter_items_by_settings(
                    list(all_candidates.values()), self.user_settings, apply_quality_band=False
                )
                logger.debug(f"Total {len(simkl_candidates)} after filtering")
            else:
                logger.debug("Simkl returned no results, falling back to TMDB")

        if not simkl_candidates:
            all_candidates = {}
            logger.debug(f"Fetching TMDB recommendations for {len(top_items)} top items")
            results = await asyncio.gather(
                *(self._fetch_recommendations_for_item(item.id, mtype) for item in top_items if item.id),
                return_exceptions=True,
            )

            for res in results:
                if isinstance(res, Exception):
                    logger.debug(f"Error fetching recommendations: {type(res).__name__}")
                    continue
                for candidate in res:
                    candidate_id = candidate.get("id")
                    if candidate_id:
                        all_candidates[candidate_id] = candidate

            logger.debug(f"Fetched {len(all_candidates)} candidates from TMDB")
            tmdb_candidates = filter_items_by_settings(list(all_candidates.values()), self.user_settings)

        candidates = simkl_candidates + tmdb_candidates

        excluded_ids = RecommendationFiltering.get_excluded_genre_ids(self.user_settings, content_type)
        filtered = filter_by_genres(candidates, watched_tmdb, excluded_ids)
        logger.debug(f"Filtered {len(filtered)} candidates")

        if profile:
            scored = [
                (RecommendationScoring.calculate_final_score(item, profile, self.scorer, mtype), item)
                for item in filtered
            ]
            scored.sort(key=lambda x: x[0], reverse=True)
            filtered = [item for _, item in scored]
        else:
            logger.debug("No profile available, sorting by popularity")
            filtered = sorted(filtered, key=lambda x: x.get("popularity", 0) * x.get("vote_average", 0), reverse=True)

        enriched = await RecommendationMetadata.fetch_batch(
            self.tmdb_service, filtered, content_type, user_settings=self.user_settings
        )
        logger.debug(f"Enriched {len(enriched)} items")

        return filter_watched_by_imdb(enriched, watched_imdb)

    async def _fetch_simkl_candidates(self, top_items: list[StremioLibraryItem], mtype: str) -> list[dict[str, Any]]:
        simkl_api_key = self.user_settings.simkl_api_key
        if not simkl_api_key:
            return []

        imdb_ids = []
        for item in top_items:
            item_id = item.id
            if item_id and item_id.startswith("tt"):
                imdb_ids.append(item_id)

        if not imdb_ids:
            logger.warning("No valid IMDB IDs found for Simkl recommendations")
            return []

        try:
            return await simkl_service.get_recommendations_batch(
                imdb_ids,
                mtype,
                simkl_api_key,
                max_per_item=8,
                year_min=self.user_settings.year_min,
                year_max=self.user_settings.year_max,
            )
        except Exception as e:
            logger.error(f"Error fetching Simkl recommendations: {type(e).__name__}")
            return []

    async def _fetch_recommendations_for_item(self, item_id: str, mtype: str) -> list[dict[str, Any]]:
        tmdb_id = await resolve_tmdb_id(item_id, self.tmdb_service)
        if not tmdb_id:
            return []

        combined = {}

        try:
            res = await self.tmdb_service.get_recommendations(tmdb_id, mtype, page=1)
            for item in res.get("results", []):
                candidate_id = item.get("id")
                if candidate_id:
                    combined[candidate_id] = item
        except Exception as e:
            logger.debug(f"Error fetching recommendations for {tmdb_id}: {type(e).__name__}")

        return list(combined.values())
