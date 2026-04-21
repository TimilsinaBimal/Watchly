import time
from typing import Any

from loguru import logger

from app.core.constants import DEFAULT_CATALOG_LIMIT, MAX_CATALOG_ITEMS
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
    """
    Generates top picks by combining multiple sources and applying diversity caps.

    Orchestrates:
    1. CandidateFetcher — gathers candidates from TMDB/Simkl/Discover
    2. RecommendationScoring — scores candidates against user profile
    3. apply_diversity_caps — ensures balanced genre/quality distribution
    4. RecommendationMetadata — enriches with full details
    5. apply_creator_cap — limits per-director/actor saturation
    """

    def __init__(self, tmdb_service: TMDBService, user_settings: UserSettings | None = None):
        self.tmdb_service: TMDBService = tmdb_service
        self.user_settings: UserSettings | None = user_settings
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
        """
        Get top picks with diversity caps.

        Strategy:
        1. Fetch candidates from all sources (TMDB recs, Simkl, Discover)
        2. Filter out watched items
        3. Score with ProfileScorer + Quality
        4. Apply diversity caps
        5. Enrich metadata with full details
        6. Apply creator cap and final filters
        """
        start_time = time.time()
        logger.info(f"Starting top picks generation for {content_type}, target limit={limit}")

        mtype = content_type_to_mtype(content_type)

        # 1. Fetch and merge all candidates
        all_candidates = await self.candidate_fetcher.fetch_all_candidates(profile, library_items, content_type, mtype)

        # 2. Filter out watched items
        filtered_candidates = [item for item in all_candidates.values() if item.get("id") not in watched_tmdb]
        logger.info(f"Found {len(filtered_candidates)} candidates after filtering out watched items and user settings")

        # 3. Score all candidates with profile
        scored_candidates = []
        for item in filtered_candidates:
            try:
                final_score = RecommendationScoring.calculate_final_score(
                    item=item,
                    profile=profile,
                    scorer=self.scorer,
                    mtype=mtype,
                )
                scored_candidates.append((final_score, item))
            except Exception as e:
                logger.debug(f"Failed to score item {item.get('id')}: {e}")
                continue

        scored_candidates.sort(key=lambda x: x[0], reverse=True)
        logger.info(f"Scored {len(scored_candidates)} candidates.")

        # 4. Apply diversity caps
        result = apply_diversity_caps(scored_candidates, len(scored_candidates), mtype, self.user_settings)
        logger.info(f"After diversity caps: {len(result)} items")

        # Limit before enrichment to avoid timeout (only enrich 3x what we need)
        result = result[: limit * 3]
        logger.info(f"After diversity caps and pre-enrichment limit: {len(result)} items")

        # 5. Enrich metadata
        enriched = await RecommendationMetadata.fetch_batch(
            self.tmdb_service, result, content_type, user_settings=self.user_settings
        )
        logger.info(f"Enriched {len(enriched)} items with full metadata")

        # 6. Final filter
        filtered = filter_watched_by_imdb(enriched, watched_imdb)

        elapsed_time = time.time() - start_time
        logger.info(
            f"Top picks complete: {len(filtered)} items returned in {elapsed_time:.2f}s "
            f"(target: {limit}, candidates: {len(all_candidates)}, scored: {len(scored_candidates)})"
        )

        return filtered[:MAX_CATALOG_ITEMS]
