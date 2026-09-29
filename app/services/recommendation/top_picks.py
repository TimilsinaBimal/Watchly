import time
from typing import Any

from loguru import logger

from app.core.constants import DEFAULT_CATALOG_LIMIT
from app.core.settings import UserSettings
from app.models.library import LibraryCollection
from app.models.profile import TasteProfile
from app.services.profile.scorer import ProfileScorer
from app.services.profile.scoring import ScoringService
from app.services.recommendation.candidate_sources import CandidateFetcher
from app.services.recommendation.diversity import apply_diversity_caps
from app.services.recommendation.scoring import RecommendationScoring
from app.services.recommendation.utils import content_type_to_mtype
from app.services.tmdb.service import TMDBService


class TopPicksService:
    """Top picks from TMDB/Simkl/Discover candidates, scored against the profile and diversity-capped."""

    def __init__(self, tmdb_service: TMDBService, user_settings: UserSettings):
        self.tmdb_service = tmdb_service
        self.user_settings = user_settings
        self.scorer: ProfileScorer = ProfileScorer()
        self.scoring_service = ScoringService()
        self.candidate_fetcher = CandidateFetcher(tmdb_service, user_settings, self.scoring_service)

    async def get_top_picks(
        self,
        profile: TasteProfile,
        content_type: str,
        library_items: LibraryCollection,
        limit: int = DEFAULT_CATALOG_LIMIT,
    ) -> list[dict[str, Any]]:
        start_time = time.time()
        logger.debug(f"Starting top picks generation for {content_type}, target limit={limit}")

        mtype = content_type_to_mtype(content_type)

        all_candidates = await self.candidate_fetcher.fetch_all_candidates(profile, library_items, content_type, mtype)

        scored_candidates = [
            (RecommendationScoring.calculate_final_score(item, profile, self.scorer, mtype), item)
            for item in all_candidates.values()
        ]
        scored_candidates.sort(key=lambda x: x[0], reverse=True)

        # 3x the target so the genre cap is meaningful and the shared filters that
        # run after this still leave headroom.
        result = apply_diversity_caps(scored_candidates, limit * 3, mtype, self.user_settings)

        logger.debug(
            f"Top picks ranked {len(result)} of {len(all_candidates)} candidates in {time.time() - start_time:.2f}s"
        )
        return result
