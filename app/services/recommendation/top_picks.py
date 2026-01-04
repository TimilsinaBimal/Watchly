import asyncio
import time
from collections import defaultdict
from datetime import date, datetime
from typing import Any

from loguru import logger

from app.core.settings import UserSettings
from app.models.taste_profile import TasteProfile
from app.services.profile.constants import (
    TOP_PICKS_CREATOR_CAP,
    TOP_PICKS_ERA_CAP,
    TOP_PICKS_GENRE_CAP,
    TOP_PICKS_MIN_RATING,
    TOP_PICKS_MIN_VOTE_COUNT,
)
from app.services.profile.sampling import SmartSampler
from app.services.profile.scorer import ProfileScorer
from app.services.recommendation.filtering import RecommendationFiltering
from app.services.recommendation.metadata import RecommendationMetadata
from app.services.recommendation.scoring import RecommendationScoring
from app.services.recommendation.utils import content_type_to_mtype, filter_watched_by_imdb, resolve_tmdb_id
from app.services.scoring import ScoringService
from app.services.tmdb.service import TMDBService


class TopPicksService:
    """
    Generates top picks by combining multiple sources and applying diversity caps.
    """

    def __init__(self, tmdb_service: TMDBService, user_settings: UserSettings | None = None):
        self.tmdb_service: TMDBService = tmdb_service
        self.user_settings: UserSettings | None = user_settings
        self.scorer: ProfileScorer = ProfileScorer()
        self.scoring_service = ScoringService()
        self.smart_sampler = SmartSampler(self.scoring_service)

    async def get_top_picks(
        self,
        profile: TasteProfile,
        content_type: str,
        library_items: dict[str, list[dict[str, Any]]],
        watched_tmdb: set[int],
        watched_imdb: set[str],
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """
        Get top picks with diversity caps.

        Strategy:
        1. Fetch recommendations from top 8 library items - 1 page each
        2. Fetch discover with profile features (genres, keywords, cast, crew, era, country)
        3. Merge all candidates (deduped by TMDB ID)
        4. Score with ProfileScorer + Quality
        5. Apply diversity caps (relaxed: 50% genre, 50% era, 15% recent)
        6. Limit to 2x target before enrichment (performance optimization)
        7. Enrich metadata with full details
        8. Apply creator cap and final filters
        9. Return balanced results

        Args:
            profile: User taste profile
            content_type: Content type (movie/series)
            library_items: Library items dict
            watched_tmdb: Set of watched TMDB IDs
            watched_imdb: Set of watched IMDB IDs
            limit: Number of items to return

        Returns:
            List of recommended items
        """

        start_time = time.time()

        logger.info(f"Starting top picks generation for {content_type}, target limit={limit}")

        mtype = content_type_to_mtype(content_type)
        all_candidates = {}

        # 1. Fetch recommendations from top items (loved/watched/liked/added)
        rec_candidates = await self._fetch_recommendations_from_top_items(library_items, content_type, mtype)
        for item in rec_candidates:
            if item.get("id"):
                all_candidates[item["id"]] = item

        # 2. Fetch discover with profile features
        discover_candidates = await self._fetch_discover_with_profile(profile, content_type, mtype)
        for item in discover_candidates:
            if item.get("id"):
                all_candidates[item["id"]] = item

        # Filter out watched items
        filtered_candidates = [item for item in all_candidates.values() if item.get("id") not in watched_tmdb]

        #  Score all candidates with profile
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

        # Sort by score
        scored_candidates.sort(key=lambda x: x[0], reverse=True)

        logger.info(f"Scored {len(scored_candidates)} candidates.")

        # Apply diversity caps
        result = self._apply_diversity_caps(scored_candidates, len(scored_candidates), mtype)
        logger.info(f"After diversity caps: {len(result)} items")

        # Limit before enrichment to avoid timeout (only enrich 3x what we need)
        result = result[: limit * 3]
        logger.info(f"After diversity caps and pre-enrichment limit: {len(result)} items")

        # Enrich metadata
        enriched = await RecommendationMetadata.fetch_batch(
            self.tmdb_service, result, content_type, user_settings=self.user_settings
        )
        logger.info(f"Enriched {len(enriched)} items with full metadata")

        # # Apply creator cap (after enrichment, we have full metadata)
        # final = self._apply_creator_cap(enriched, len(enriched))
        # logger.info(f"After creator cap: {len(final)} items")

        # Final filter (remove watched by IMDB ID)
        filtered = filter_watched_by_imdb(enriched, watched_imdb)

        elapsed_time = time.time() - start_time
        logger.info(
            f"✓ Top picks complete: {len(filtered)} items returned in {elapsed_time:.2f}s "
            f"(target: {limit}, candidates: {len(all_candidates)}, scored: {len(scored_candidates)})"
        )

        return filtered

    async def _fetch_recommendations_from_top_items(
        self, library_items: dict[str, list[dict[str, Any]]], content_type: str, mtype: str
    ) -> list[dict[str, Any]]:
        """
        Fetch recommendations from top items (loved/watched/liked/added).

        Args:
            library_items: Library items dict
            content_type: Content type
            mtype: TMDB media type (movie/tv)

        Returns:
            List of candidate items
        """
        # Get top items (loved first, then liked, then added, then top watched)
        top_items = self.smart_sampler.sample_items(library_items, content_type, max_items=15)

        candidates = []
        tasks = []

        for item in top_items:
            item = item.item
            item_id = item.id
            if not item_id:
                continue

            # Resolve TMDB ID
            tmdb_id = await resolve_tmdb_id(item_id, self.tmdb_service)
            if not tmdb_id:
                continue

            # Fetch recommendations (1 page only)
            tasks.append(self.tmdb_service.get_recommendations(tmdb_id, mtype, page=1))
            # tasks.append(self.tmdb_service.get_similar(tmdb_id, mtype, page=1))

        # Execute all in parallel
        logger.debug(f"Fetching recommendations from {len(tasks)} top library items")
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

    def _add_discover_task(self, tasks: list, mtype: str, without_genres: str | None, **kwargs: Any) -> None:
        """
        Add a discover task to the list of tasks with default parameters.
        """
        params = {
            "sort_by": "popularity.asc",
            "vote_count_gte": TOP_PICKS_MIN_VOTE_COUNT,
            "vote_average_gte": TOP_PICKS_MIN_RATING,
            **kwargs,
        }
        if without_genres:
            params["without_genres"] = without_genres
        tasks.append(self.tmdb_service.get_discover(mtype, **params))

    async def _fetch_discover_with_profile(
        self, profile: TasteProfile, content_type: str, mtype: str
    ) -> list[dict[str, Any]]:
        """
        Fetch discover results using profile features.

        Args:
            profile: User taste profile
            content_type: Content type
            mtype: TMDB media type

        Returns:
            List of candidate items
        """

        excluded_genre_ids = RecommendationFiltering.get_excluded_genre_ids(self.user_settings, content_type)
        without_genres = "|".join(str(g) for g in excluded_genre_ids) if excluded_genre_ids else None

        logger.debug(f"Excluded genres for {content_type}: {excluded_genre_ids}")

        # Get top features from profile
        top_genres = profile.get_top_genres(limit=5)
        top_keywords = profile.get_top_keywords(limit=5)
        top_directors = profile.get_top_directors(limit=3)
        top_cast = profile.get_top_cast(limit=5)
        top_eras = profile.get_top_eras(limit=2)
        top_countries = profile.get_top_countries(limit=5)

        candidates = []
        tasks = []

        # Discover with genres
        if top_genres:
            genre_ids = [g[0] for g in top_genres]
            self._add_discover_task(
                tasks, mtype, without_genres, with_genres="|".join(str(g) for g in genre_ids), page=1
            )

        # Discover with keywords
        if top_keywords:
            keyword_ids = [k[0] for k in top_keywords]
            for page in range(1, 3):  # 2 pages
                self._add_discover_task(
                    tasks, mtype, without_genres, with_keywords="|".join(str(k) for k in keyword_ids), page=page
                )

        # Discover with directors
        if top_directors:
            director_ids = [d[0] for d in top_directors]
            self._add_discover_task(
                tasks, mtype, without_genres, with_crew="|".join(str(d) for d in director_ids), page=1
            )

        # Discover with cast
        if top_cast:
            cast_ids = [c[0] for c in top_cast]
            self._add_discover_task(tasks, mtype, without_genres, with_cast="|".join(str(c) for c in cast_ids), page=1)

        # Discover with era (year range)
        if top_eras:
            era = top_eras[0][0]
            year_start = self._era_to_year_start(era)
            if year_start:
                prefix = "first_air_date" if mtype == "tv" else "primary_release_date"
                lte_prefix = date.today().isoformat() if year_start + 9 > date.today().year else f"{year_start+9}-12-31"
                params = {
                    f"{prefix}.gte": f"{year_start}-01-01",
                    f"{prefix}.lte": lte_prefix,
                    "page": 1,
                }

                self._add_discover_task(tasks, mtype, without_genres, **params)

        # Discover with countries
        if top_countries:
            country_codes = [c[0] for c in top_countries]
            params = {
                "with_origin_country": "|".join(country_codes),
                "page": 1,
            }
            self._add_discover_task(tasks, mtype, without_genres, **params)

        # Execute all in parallel
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

    async def _fetch_trending_and_popular(self, content_type: str, mtype: str) -> list[dict[str, Any]]:
        """
        Fetch trending and popular items (for recent items injection).

        Args:
            content_type: Content type
            mtype: TMDB media type

        Returns:
            List of candidate items
        """
        candidates = []

        # Fetch trending (1 page)
        try:
            trending = await self.tmdb_service.get_trending(mtype, time_window="week", page=1)
            candidates.extend(trending.get("results", []))
        except Exception as e:
            logger.debug(f"Failed to fetch trending: {e}")

        return candidates

    def _apply_diversity_caps(
        self, scored_candidates: list[tuple[float, dict[str, Any]]], limit: int, mtype: str
    ) -> list[dict[str, Any]]:
        """
        Apply diversity caps to ensure balanced results.

        Caps:
        - Genre: max 50% per genre
        - Era: max 50% per era
        - Quality: minimum vote_count and rating

        Args:
            scored_candidates: List of (score, item) tuples, sorted by score
            limit: Target number of items
            mtype: Media type for quality checks

        Returns:
            Filtered and capped list of items
        """
        result = []
        genre_counts = defaultdict(int)
        era_counts = defaultdict(int)

        max_per_genre = int(limit * TOP_PICKS_GENRE_CAP)
        max_per_era = int(limit * TOP_PICKS_ERA_CAP)

        for score, item in scored_candidates:
            if len(result) >= limit:
                break

            item_id = item.get("id")
            if not item_id:
                continue

            # Quality threshold
            vote_count = item.get("vote_count", 0)
            vote_avg = item.get("vote_average", 0)
            if vote_count < TOP_PICKS_MIN_VOTE_COUNT:
                continue

            wr = RecommendationScoring.weighted_rating(vote_avg, vote_count, C=7.2 if mtype == "tv" else 6.8)
            if wr < TOP_PICKS_MIN_RATING:
                continue

            # Check genre cap (50% max per genre)
            genre_ids = item.get("genre_ids", [])
            if genre_ids:
                top_genre = genre_ids[0]  # Primary genre
                if genre_counts[top_genre] >= max_per_genre:
                    continue

            # Check era cap (50% max per era)
            year = self._extract_year(item)
            if year:
                era = self._year_to_era(year)
                if era_counts[era] >= max_per_era:
                    continue

            # Add item
            result.append(item)

            if genre_ids:
                genre_counts[top_genre] += 1
            if year:
                era = self._year_to_era(year)
                era_counts[era] += 1

        return result

    def _apply_creator_cap(self, items: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
        """
        Apply creator cap (max 2 items per director/actor) after enrichment.

        Args:
            items: List of enriched items with full metadata
            limit: Target limit

        Returns:
            Filtered list respecting creator cap
        """
        result = []
        creator_counts = defaultdict(int)

        for item in items:
            if len(result) >= limit:
                break

            # Extract creators from credits
            credits = item.get("credits", {}) or {}
            crew = credits.get("crew", []) or []
            cast = credits.get("cast", []) or []

            # Check director cap
            directors = [c.get("id") for c in crew if c.get("job", "").lower() == "director" and c.get("id")]
            blocked_by_director = False
            for dir_id in directors:
                if creator_counts[dir_id] >= TOP_PICKS_CREATOR_CAP:
                    blocked_by_director = True
                    break

            # Check cast cap (top 3 only)
            top_cast = [c.get("id") for c in cast[:3] if c.get("id")]
            blocked_by_cast = False
            for cast_id in top_cast:
                if creator_counts[cast_id] >= TOP_PICKS_CREATOR_CAP:
                    blocked_by_cast = True
                    break

            if blocked_by_director or blocked_by_cast:
                continue

            # Add item
            result.append(item)

            # Update creator counts
            for dir_id in directors:
                creator_counts[dir_id] += 1
            for cast_id in top_cast:
                creator_counts[cast_id] += 1

        return result

    @staticmethod
    def _extract_year(item: dict[str, Any]) -> int | None:
        """Extract year from item."""
        release_date = item.get("release_date") or item.get("first_air_date")
        if release_date:
            try:
                return int(str(release_date)[:4])
            except (ValueError, TypeError):
                pass
        return None

    @staticmethod
    def _is_recent_release(item: dict[str, Any], threshold: datetime, mtype: str) -> bool:
        """Check if item was released within the threshold (e.g., last 6 months)."""
        release_date_str = item.get("release_date") if mtype == "movie" else item.get("first_air_date")
        if not release_date_str:
            return False

        try:
            # Parse release date (format: YYYY-MM-DD)
            release_date = datetime.strptime(str(release_date_str)[:10], "%Y-%m-%d")
            return release_date >= threshold
        except (ValueError, TypeError):
            return False

    @staticmethod
    def _year_to_era(year: int) -> str:
        """Convert year to era bucket."""
        if year < 1970:
            return "pre-1970s"
        elif year < 1980:
            return "1970s"
        elif year < 1990:
            return "1990s"
        elif year < 2000:
            return "2000s"
        elif year < 2010:
            return "2010s"
        elif year < 2020:
            return "2020s"
        else:
            return "2020s"

    @staticmethod
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
