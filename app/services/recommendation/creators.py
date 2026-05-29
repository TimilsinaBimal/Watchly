import asyncio
from typing import Any

from fastapi import HTTPException
from loguru import logger

from app.core.settings import UserSettings
from app.models.profile import TasteProfile
from app.services.recommendation.filtering import RecommendationFiltering, filter_watched_by_imdb
from app.services.recommendation.metadata import RecommendationMetadata
from app.services.recommendation.utils import content_type_to_mtype
from app.services.tmdb.service import TMDBService

SMALL_LIBRARY_THRESHOLD = 5
DIRECTOR_LIMIT = 3
CAST_LIMIT = 3
MIN_FREQUENCY = 2


class CreatorsService:
    """Recommendations from creators the user actually returns to.

    A "favorite" creator is someone the user has watched across multiple
    items, not just whoever made their last watch. With a sparse library
    (1–3 items) every director and lead cast member trivially looks like
    a "top creator", which made the old top-N-by-score selection feel
    like "more from that one movie I watched". This service filters by
    raw appearance frequency (`director_frequency` / `cast_frequency`
    persisted on the profile) before fetching:

    * Cast: strict freq >= 2. A movie contributes the top 3 cast, so any
      user with two watched items has a real chance of overlap; if no
      actor recurs, the cast half of the catalog is empty.
    * Directors: freq >= 2 preferred. As a small-library safety net,
      when the profile has fewer than 5 processed items and nobody
      recurs, fall back to the single highest-scored director so brand
      new users still see a row. Once the library grows past the
      threshold, "no recurring directors" is honest signal — the
      catalog hides itself.

    If neither half qualifies, raise 404 (Stremio will hide the row).
    """

    def __init__(self, tmdb_service: TMDBService, user_settings: UserSettings | None = None):
        self.tmdb_service: TMDBService = tmdb_service
        self.user_settings: UserSettings | None = user_settings

    @staticmethod
    def _select_recurring(
        score_pairs: list[tuple[int, float]],
        frequency: dict[int, int],
        limit: int,
    ) -> list[tuple[int, float]]:
        """Keep score-sorted creators whose appearance count meets the threshold."""
        return [(cid, score) for cid, score in score_pairs if frequency.get(cid, 0) >= MIN_FREQUENCY][:limit]

    def _select_directors(self, profile: TasteProfile) -> list[tuple[int, float]]:
        all_directors = sorted(profile.director_scores.items(), key=lambda kv: kv[1], reverse=True)
        recurring = self._select_recurring(all_directors, profile.director_frequency, DIRECTOR_LIMIT)
        if recurring:
            return recurring
        # Small-library fallback: brand-new users haven't had a chance to
        # rewatch anyone yet, so seeding from their top-scored director is
        # better than an empty catalog. Larger libraries with no recurrence
        # legitimately have no "favorite" director — let the catalog hide.
        if len(profile.processed_items) < SMALL_LIBRARY_THRESHOLD and all_directors:
            return all_directors[:1]
        return []

    def _select_cast(self, profile: TasteProfile) -> list[tuple[int, float]]:
        all_cast = sorted(profile.cast_scores.items(), key=lambda kv: kv[1], reverse=True)
        return self._select_recurring(all_cast, profile.cast_frequency, CAST_LIMIT)

    async def get_recommendations_from_creators(
        self,
        profile: TasteProfile,
        content_type: str,
        watched_tmdb: set[int],
        watched_imdb: set[str],
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        mtype = content_type_to_mtype(content_type)

        selected_directors = self._select_directors(profile)
        selected_cast = self._select_cast(profile)

        if not selected_directors and not selected_cast:
            raise HTTPException(status_code=404, detail="No recurring directors or cast in profile")

        logger.info(
            f"Creators catalog: {len(selected_directors)} directors, {len(selected_cast)} cast "
            f"(profile has {len(profile.processed_items)} processed items)"
        )

        min_rating, min_votes = RecommendationFiltering.get_quality_thresholds(self.user_settings)
        all_candidates = {}
        tasks = []

        for dir_id, _ in selected_directors:
            for page in [1, 2]:
                # TMDB /discover supports with_crew for both movies and TV;
                # with_people is a search-people endpoint param, not valid here.
                discover_params = {
                    "with_crew": str(dir_id),
                    "page": page,
                    "vote_count.gte": min_votes,
                    "vote_average.gte": min_rating,
                }
                tasks.append(self._fetch_discover_page(mtype, discover_params, dir_id, "director"))

        for cast_id, _ in selected_cast:
            for page in [1, 2]:
                discover_params = {
                    "with_cast": str(cast_id),
                    "page": page,
                    "vote_count.gte": min_votes,
                    "vote_average.gte": min_rating,
                }
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

        return final

    async def _fetch_discover_page(
        self,
        mtype: str,
        discover_params: dict[str, Any],
        creator_id: int,
        creator_type: str,
    ) -> list[dict[str, Any]]:
        try:
            results = await self.tmdb_service.get_discover(mtype, **discover_params)
            return results.get("results", [])
        except Exception as e:
            logger.debug(f"Error fetching recommendations for {creator_type} {creator_id}: {e}")
            return []
