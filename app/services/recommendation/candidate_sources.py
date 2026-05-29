import asyncio
from datetime import date
from typing import Any

from loguru import logger

from app.core.settings import UserSettings
from app.models.library import LibraryCollection
from app.models.profile import TasteProfile
from app.services.profile.sampling import sample_items
from app.services.profile.scoring import ScoringService
from app.services.recommendation.filtering import (
    RecommendationFiltering,
    apply_discover_filters,
    filter_items_by_settings,
)
from app.services.recommendation.utils import resolve_tmdb_id
from app.services.simkl import simkl_service
from app.services.tmdb.service import TMDBService


def _era_to_year_start(era: str) -> int | None:
    """Convert era bucket to starting year."""
    era_map = {
        "pre-1970s": 1950,
        "1970s": 1970,
        "1980s": 1980,
        "1990s": 1990,
        "2000s": 2000,
        "2010s": 2010,
        "2020s": 2020,
    }
    return era_map.get(era)


class CandidateFetcher:
    """Fetches recommendation candidates from multiple sources (TMDB, Simkl, Discover)."""

    def __init__(
        self,
        tmdb_service: TMDBService,
        user_settings: UserSettings | None = None,
        scoring_service: ScoringService | None = None,
    ):
        self.tmdb_service = tmdb_service
        self.user_settings = user_settings
        self.scoring_service = scoring_service or ScoringService()

    async def fetch_recommendations_from_top_items(
        self,
        library_items: LibraryCollection,
        content_type: str,
        mtype: str,
    ) -> list[dict[str, Any]]:
        """Fetch recommendations from top items (loved/watched/liked/added)."""
        top_items = sample_items(library_items, content_type, self.scoring_service, max_items=15)

        candidates = []
        tasks = []

        for item in top_items:
            item = item.item
            item_id = item.id
            if not item_id:
                continue

            tmdb_id = await resolve_tmdb_id(item_id, self.tmdb_service)
            if not tmdb_id:
                continue

            tasks.append(self.tmdb_service.get_recommendations(tmdb_id, mtype, page=1))

        logger.info(f"Fetching recommendations from {len(tasks)} top library items")
        results = await asyncio.gather(*tasks, return_exceptions=True)

        failed_count = 0
        for res in results:
            if isinstance(res, Exception):
                failed_count += 1
                logger.debug(f"Recommendation fetch failed: {res}")
                continue
            candidates.extend(res.get("results", []))

        if failed_count > 0:
            logger.info(f"{failed_count}/{len(tasks)} recommendation fetches failed (expected for items with no recs)")
        logger.debug(f"Fetched {len(candidates)} candidates from top items")

        return candidates

    async def fetch_simkl_recommendations(
        self,
        library_items: LibraryCollection,
        content_type: str,
        mtype: str,
    ) -> list[dict[str, Any]]:
        """Fetch recommendations from Simkl for top library items."""
        simkl_api_key = self.user_settings.simkl_api_key if self.user_settings else None
        if not simkl_api_key:
            logger.warning("Simkl API key not found, skipping Simkl recommendations")
            return []

        top_items = sample_items(library_items, content_type, self.scoring_service, max_items=15)

        imdb_ids = []
        for scored_item in top_items:
            item_id = scored_item.item.id
            if item_id and item_id.startswith("tt"):
                imdb_ids.append(item_id)

        if not imdb_ids:
            logger.warning("No valid IMDB IDs found for Simkl recommendations")
            return []

        logger.info(f"Fetching Simkl recommendations for {len(imdb_ids)} items")

        year_min = getattr(self.user_settings, "year_min", None)
        year_max = getattr(self.user_settings, "year_max", None)

        try:
            candidates = await simkl_service.get_recommendations_batch(
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

        logger.info(f"Fetched {len(candidates)} candidates from Simkl")
        return candidates

    def _add_discover_task(self, tasks: list, mtype: str, without_genres: str | None, **kwargs: Any) -> None:
        """Add a discover task to the list of tasks with default parameters."""
        sort_by = RecommendationFiltering.get_sort_by_preference(self.user_settings)
        params = {
            "sort_by": sort_by,
            **kwargs,
        }
        if without_genres:
            params["without_genres"] = without_genres

        params = apply_discover_filters(params, self.user_settings)
        tasks.append(self.tmdb_service.get_discover(mtype, **params))

    async def fetch_discover_with_profile(
        self, profile: TasteProfile, content_type: str, mtype: str
    ) -> list[dict[str, Any]]:
        """Fetch discover results using profile features."""
        excluded_genre_ids = RecommendationFiltering.get_excluded_genre_ids(self.user_settings, content_type)
        without_genres = "|".join(str(g) for g in excluded_genre_ids) if excluded_genre_ids else None

        logger.debug(f"Excluded genres for {content_type}: {excluded_genre_ids}")

        top_genres = profile.get_top_genres(limit=5)
        top_keywords = profile.get_top_keywords(limit=5)
        top_directors = profile.get_top_directors(limit=3)
        top_cast = profile.get_top_cast(limit=5)
        top_eras = profile.get_top_eras(limit=2)
        top_countries = profile.get_top_countries(limit=5)

        candidates = []
        tasks = []

        if top_genres:
            genre_ids = [g[0] for g in top_genres]
            self._add_discover_task(
                tasks,
                mtype,
                without_genres,
                with_genres="|".join(str(g) for g in genre_ids),
                page=1,
            )

        if top_keywords:
            keyword_ids = [k[0] for k in top_keywords]
            for page in range(1, 3):
                self._add_discover_task(
                    tasks,
                    mtype,
                    without_genres,
                    with_keywords="|".join(str(k) for k in keyword_ids),
                    page=page,
                )

        if top_directors:
            director_ids = [d[0] for d in top_directors]
            self._add_discover_task(
                tasks,
                mtype,
                without_genres,
                with_crew="|".join(str(d) for d in director_ids),
                page=1,
            )

        if top_cast:
            cast_ids = [c[0] for c in top_cast]
            self._add_discover_task(
                tasks,
                mtype,
                without_genres,
                with_cast="|".join(str(c) for c in cast_ids),
                page=1,
            )

        if top_eras:
            era = top_eras[0][0]
            year_start = _era_to_year_start(era)
            if year_start:
                prefix = "first_air_date" if mtype == "tv" else "primary_release_date"
                lte_prefix = (
                    date.today().isoformat() if year_start + 9 > date.today().year else f"{year_start + 9}-12-31"
                )
                params = {
                    f"{prefix}.gte": f"{year_start}-01-01",
                    f"{prefix}.lte": lte_prefix,
                    "page": 1,
                }
                self._add_discover_task(tasks, mtype, without_genres, **params)

        if top_countries:
            country_codes = [c[0] for c in top_countries]
            params = {
                "with_origin_country": "|".join(country_codes),
                "page": 1,
            }
            self._add_discover_task(tasks, mtype, without_genres, **params)

        logger.debug(f"Fetching {len(tasks)} discover queries with profile features")
        results = await asyncio.gather(*tasks, return_exceptions=True)

        failed_count = 0
        for res in results:
            if isinstance(res, Exception):
                failed_count += 1
                logger.warning(f"Discover query failed: {res}")
                continue
            candidates.extend(res.get("results", []))

        if failed_count > 0:
            logger.warning(f"{failed_count}/{len(tasks)} discover queries failed")
        logger.debug(f"Fetched {len(candidates)} candidates from discover")

        return candidates

    async def fetch_trending_and_popular(self, content_type: str, mtype: str) -> list[dict[str, Any]]:
        """Fetch trending and popular items (for recent items injection)."""
        candidates = []
        try:
            trending = await self.tmdb_service.get_trending(mtype, time_window="week", page=1)
            candidates.extend(trending.get("results", []))
        except Exception as e:
            logger.debug(f"Failed to fetch trending: {e}")

        return candidates

    async def fetch_all_candidates(
        self,
        profile: TasteProfile,
        library_items: LibraryCollection,
        content_type: str,
        mtype: str,
    ) -> dict[int, dict[str, Any]]:
        """Fetch and merge candidates from all sources, deduped by TMDB ID."""
        all_candidates: dict[int, dict[str, Any]] = {}

        # 1. Fetch recommendations from top items
        simkl_api_key = self.user_settings.simkl_api_key if self.user_settings else None
        if simkl_api_key:
            rec_candidates = await self.fetch_simkl_recommendations(library_items, content_type, mtype)
            if not rec_candidates:
                logger.info("Simkl returned no results, falling back to TMDB")
                rec_candidates = await self.fetch_recommendations_from_top_items(library_items, content_type, mtype)
                rec_candidates = filter_items_by_settings(rec_candidates, self.user_settings, simkl=True)
        else:
            rec_candidates = await self.fetch_recommendations_from_top_items(library_items, content_type, mtype)
            rec_candidates = filter_items_by_settings(rec_candidates, self.user_settings)

        for item in rec_candidates:
            if item.get("id"):
                all_candidates[item["id"]] = item

        # 2. Fetch discover with profile features
        discover_candidates = await self.fetch_discover_with_profile(profile, content_type, mtype)
        discover_candidates = filter_items_by_settings(discover_candidates, self.user_settings)
        for item in discover_candidates:
            if item.get("id"):
                all_candidates[item["id"]] = item

        return all_candidates
