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
from app.services.recommendation.filtering import filter_watched_by_imdb
from app.services.recommendation.metadata import RecommendationMetadata
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
        watched_tmdb: set[int],
        watched_imdb: set[str],
        limit: int = DEFAULT_CATALOG_LIMIT,
    ) -> list[dict[str, Any]]:
        start_time = time.time()
        logger.debug(f"Starting top picks generation for {content_type}, target limit={limit}")

        mtype = content_type_to_mtype(content_type)

        all_candidates = await self.candidate_fetcher.fetch_all_candidates(profile, library_items, content_type, mtype)

        filtered_candidates = [item for item in all_candidates.values() if item.get("id") not in watched_tmdb]
        logger.debug(f"Found {len(filtered_candidates)} candidates after filtering out watched items and user settings")

        scored_candidates = [
            (RecommendationScoring.calculate_final_score(item, profile, self.scorer, mtype), item)
            for item in filtered_candidates
        ]
        scored_candidates.sort(key=lambda x: x[0], reverse=True)

        # 3x the target so the genre cap is meaningful and the post-enrichment
        # filters still have headroom.
        diversity_target = limit * 3
        result = apply_diversity_caps(scored_candidates, diversity_target, mtype, self.user_settings)
        logger.debug(f"After diversity caps: {len(result)} items")

        enriched = await RecommendationMetadata.fetch_batch(
            self.tmdb_service, result, content_type, user_settings=self.user_settings
        )
        logger.debug(f"Enriched {len(enriched)} items with full metadata")

        filtered = filter_watched_by_imdb(enriched, watched_imdb)

        elapsed_time = time.time() - start_time
        logger.info(
            f"Top picks complete: {len(filtered)} items returned in {elapsed_time:.2f}s "
            f"(target: {limit}, candidates: {len(all_candidates)}, scored: {len(scored_candidates)})"
        )

        return filtered
