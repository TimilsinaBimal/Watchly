import asyncio
from typing import Any

from loguru import logger

from app.models.taste_profile import TasteProfile
from app.services.profile.scorer import ProfileScorer
from app.services.recommendation.filtering import RecommendationFiltering
from app.services.recommendation.metadata import RecommendationMetadata
from app.services.recommendation.scoring import RecommendationScoring
from app.services.recommendation.utils import content_type_to_mtype, filter_by_genres, filter_watched_by_imdb


class ThemeBasedService:
    """
    Handles theme-based recommendations (genre+keyword, keyword+keyword, etc.).

    Strategy:
    1. Parse theme ID to extract filters (genres, keywords, country, year)
    2. Fetch from TMDB discover API (multiple pages based on excluded genres)
    3. Score candidates with ProfileScorer (similarity + quality)
    4. Filter watched/excluded genres
    5. Return ranked results
    """

    def __init__(self, tmdb_service: Any, user_settings: Any = None):
        self.tmdb_service = tmdb_service
        self.user_settings = user_settings
        self.scorer = ProfileScorer()

    async def get_recommendations_for_theme(
        self,
        theme_id: str,
        content_type: str,
        profile: TasteProfile | None = None,
        watched_tmdb: set[int] | None = None,
        watched_imdb: set[str] | None = None,
        limit: int = 20,
        whitelist: set[int] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Get recommendations for a theme (genre+keyword, etc.).

        Args:
            theme_id: Theme ID (e.g., "watchly.theme.g123.k456")
            content_type: Content type (movie/series)
            profile: Optional profile for scoring (if None, uses popularity only)
            watched_tmdb: Set of watched TMDB IDs
            watched_imdb: Set of watched IMDB IDs
            limit: Number of items to return

        Returns:
            List of recommended items
        """
        watched_tmdb = watched_tmdb or set()
        watched_imdb = watched_imdb or set()

        # Parse theme ID to extract filters
        params = self._parse_theme_id(theme_id, content_type)

        # Add excluded genres
        excluded_ids = RecommendationFiltering.get_excluded_genre_ids(self.user_settings, content_type)
        if excluded_ids:
            with_ids = set()
            if params.get("with_genres"):
                try:
                    with_ids = {int(g) for g in params["with_genres"].split("|") if g}
                except Exception:
                    pass
            final_without = [g for g in excluded_ids if g not in with_ids]
            if final_without:
                params["without_genres"] = "|".join(str(g) for g in final_without)

        # Determine pages to fetch based on excluded genres
        pages_to_fetch = self._calculate_pages_to_fetch(len(excluded_ids))

        # Fetch candidates
        candidates = await self._fetch_discover_candidates(content_type, params, pages_to_fetch)

        # Use provided whitelist (or empty set if not provided)
        whitelist = whitelist or set()

        # Initial filter (watched + genre whitelist)
        filtered = self._filter_candidates(candidates, watched_tmdb, whitelist)

        # If not enough candidates, fetch more pages
        if len(filtered) < limit * 2 and max(pages_to_fetch) < 15:
            additional_pages = list(range(max(pages_to_fetch) + 1, min(max(pages_to_fetch) + 6, 20)))
            if additional_pages:
                additional_candidates = await self._fetch_discover_candidates(content_type, params, additional_pages)
                existing_ids = {it.get("id") for it in filtered}
                additional_filtered = self._filter_candidates(
                    additional_candidates, watched_tmdb, whitelist, existing_ids
                )
                filtered.extend(additional_filtered)

        # Score with profile if available
        if profile:
            scored = []
            mtype = content_type_to_mtype(content_type)
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

        return final

    def _parse_theme_id(self, theme_id: str, content_type: str) -> dict[str, Any]:
        """
        Parse theme ID to extract discover API parameters.

        Format: watchly.theme.g123.k456.ctUS.y1990

        Args:
            theme_id: Theme ID string
            content_type: Content type for date field selection

        Returns:
            Dictionary of discover API parameters
        """
        params = {}
        parts = theme_id.replace("watchly.theme.", "").split(".")

        for part in parts:
            if part.startswith("g"):
                # Genres: g123 or g123-456
                genre_str = part[1:].replace("-", ",")
                params["with_genres"] = genre_str.replace(",", "|")
            elif part.startswith("k"):
                # Keywords: k123 or k123-456
                kw_str = part[1:].replace("-", "|")
                params["with_keywords"] = kw_str
            elif part.startswith("ct"):
                # Country: ctUS
                params["with_origin_country"] = part[2:]
            elif part.startswith("y"):
                # Year: y1990 (decade)
                try:
                    year = int(part[1:])
                    is_tv = content_type in ("tv", "series")
                    prefix = "first_air_date" if is_tv else "primary_release_date"
                    params[f"{prefix}.gte"] = f"{year}-01-01"
                    params[f"{prefix}.lte"] = f"{year+9}-12-31"
                except Exception:
                    pass
            elif part == "sort-vote":
                params["sort_by"] = "vote_average.desc"
                params["vote_count.gte"] = 200

        # Default sort
        if "sort_by" not in params:
            params["sort_by"] = "popularity.desc"

        return params

    def _calculate_pages_to_fetch(self, num_excluded_genres: int) -> list[int]:
        """
        Calculate how many pages to fetch based on excluded genres.

        Args:
            num_excluded_genres: Number of excluded genres

        Returns:
            List of page numbers to fetch
        """
        if num_excluded_genres > 10:
            return list(range(1, 11))  # 10 pages
        elif num_excluded_genres > 5:
            return list(range(1, 6))  # 5 pages
        else:
            return [1, 2, 3]  # 3 pages

    async def _fetch_discover_candidates(
        self, content_type: str, params: dict[str, Any], pages: list[int]
    ) -> list[dict[str, Any]]:
        """
        Fetch candidates from TMDB discover API.

        Args:
            content_type: Content type
            params: Discover API parameters
            pages: List of page numbers to fetch

        Returns:
            List of candidate items
        """
        candidates = []
        tasks = [self.tmdb_service.get_discover(content_type, page=p, **params) for p in pages]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for res in results:
            if isinstance(res, Exception):
                logger.debug(f"Error fetching discover: {res}")
                continue
            candidates.extend(res.get("results", []))

        return candidates

    def _filter_candidates(
        self,
        candidates: list[dict[str, Any]],
        watched_tmdb: set[int],
        whitelist: set[int],
        existing_ids: set[int] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Filter candidates by watched items and genre whitelist.

        Args:
            candidates: List of candidate items
            watched_tmdb: Set of watched TMDB IDs
            whitelist: Set of genre IDs in whitelist
            existing_ids: Set of IDs to exclude (for deduplication)

        Returns:
            Filtered list of items
        """
        existing = existing_ids or set()
        # First filter by genres (includes watched_tmdb check)
        filtered = filter_by_genres(candidates, watched_tmdb, whitelist, None)
        # Then deduplicate
        result = []
        for item in filtered:
            item_id = item.get("id")
            if item_id and item_id not in existing:
                result.append(item)
                existing.add(item_id)
        return result
