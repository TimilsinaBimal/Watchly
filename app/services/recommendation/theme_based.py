import asyncio
from typing import Any

from loguru import logger

from app.models.taste_profile import TasteProfile
from app.services.profile.constants import (
    RUNTIME_BUCKET_MEDIUM_MAX_MOVIE,
    RUNTIME_BUCKET_MEDIUM_MAX_SERIES,
    RUNTIME_BUCKET_SHORT_MAX_MOVIE,
    RUNTIME_BUCKET_SHORT_MAX_SERIES,
)
from app.services.profile.scorer import ProfileScorer
from app.services.recommendation.filtering import RecommendationFiltering
from app.services.recommendation.metadata import RecommendationMetadata
from app.services.recommendation.scoring import RecommendationScoring
from app.services.recommendation.utils import (
    apply_discover_filters,
    content_type_to_mtype,
    filter_by_genres,
    filter_watched_by_imdb,
)
from app.services.tmdb.service import TMDBService


class ThemeBasedService:
    """
    Handles theme-based recommendations using role-based axis recipes.

    Strategy:
    1. Parse role-based theme ID (a: anchor, f: flavor, b: fallback)
    2. Primary discovery using Anchors
    3. Weighted scoring: anchor (1.0) + flavor (0.7) + fallback (0.3)
    4. Profile-aware ranking
    5. Expansion logic if results are sparse
    """

    def __init__(self, tmdb_service: Any, user_settings: Any = None):
        self.tmdb_service: TMDBService = tmdb_service
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
        """Get recommendations for a role-based theme."""
        watched_tmdb = watched_tmdb or set()
        watched_imdb = watched_imdb or set()

        # 1. Parse roles and values
        anchors, flavors, fallbacks = self._parse_theme_id(theme_id)

        # 2. Prepare common excluded genres
        excluded_ids = RecommendationFiltering.get_excluded_genre_ids(self.user_settings, content_type)

        # 3. Parallel Fetching (Intersection + Individual Anchors)
        fetch_tasks = []

        # Seed 1: The 'Perfect Match' (AND logic) - High Priority
        if len(anchors) > 1:
            combined_p = self._axes_to_params(anchors, content_type)
            if excluded_ids:
                with_ids = {int(g) for g in combined_p.get("with_genres", "").split("|") if g}
                without = [g for g in excluded_ids if g not in with_ids]
                if without:
                    combined_p["without_genres"] = "|".join(str(g) for g in without)
            fetch_tasks.append(self._fetch_discover_candidates(content_type, combined_p, pages=[1, 2, 3]))

        perfect_match_results = await asyncio.gather(*fetch_tasks, return_exceptions=True)
        perfect_match_candidates = []
        for res in perfect_match_results:
            if isinstance(res, list):
                perfect_match_candidates.extend(res)

        if len(perfect_match_candidates) < 2 * limit:
            fetch_tasks = []
            # Seeds 2+: Individual Anchors (OR logic for fullness)
            seed_axes = list(anchors.items()) if anchors else [(None, None)]
            for name, val in seed_axes:
                p = self._axes_to_params({name: val} if name else {}, content_type)
                if excluded_ids:
                    with_ids = {int(g) for g in p.get("with_genres", "").split("|") if g}
                    without = [g for g in excluded_ids if g not in with_ids]
                    if without:
                        p["without_genres"] = "|".join(str(g) for g in without)

                fetch_tasks.append(self._fetch_discover_candidates(content_type, p, pages=[1, 2]))

        # 4. Execute and Merge
        results = await asyncio.gather(*fetch_tasks, return_exceptions=True)
        candidates = []
        for res in results:
            if isinstance(res, list):
                candidates.extend(res)

        candidates = perfect_match_candidates + candidates

        # 5. Expansion Logic if sparse
        if len(candidates) < limit and anchors:
            # Expansion strategy: Relax constraints on the primary anchor
            primary_axis = dict([next(iter(anchors.items()))])
            base_p = self._axes_to_params(primary_axis, content_type)
            expanded = await self._expand_search(content_type, base_p, anchors, flavors)
            candidates.extend(expanded)

        # 6. Weighted Scoring
        scored = []
        rotation_seed = RecommendationScoring.generate_rotation_seed()
        mtype = content_type_to_mtype(content_type)

        for item in candidates:
            # Theme Match Score
            theme_match = self._calculate_theme_score(item, anchors, flavors, fallbacks)

            # Profile & Quality Score
            if profile:
                base_score = RecommendationScoring.calculate_final_score(
                    item=item,
                    profile=profile,
                    scorer=self.scorer,
                    mtype=mtype,
                    rotation_seed=rotation_seed,
                )
            else:
                base_score = RecommendationScoring.normalize(item.get("vote_average", 0))

            # Combine: theme match is the primary sorter for catalog rows
            final_score = (theme_match * 0.7) + (base_score * 0.3)

            scored.append((final_score, item))

        # 7. Rank and Enrich
        scored.sort(key=lambda x: x[0], reverse=True)
        unique_results = []
        seen = set()
        for _, item in scored:
            if item["id"] not in seen and item["id"] not in watched_tmdb:
                unique_results.append(item)
                seen.add(item["id"])
            if len(unique_results) >= limit * 2:
                break

        enriched = await RecommendationMetadata.fetch_batch(
            self.tmdb_service, unique_results, content_type, user_settings=self.user_settings
        )
        return filter_watched_by_imdb(enriched, watched_imdb)[:limit]

    def _parse_theme_id(self, theme_id: str) -> tuple[dict, dict, dict]:
        """Parse role-based ID: watchly.theme.a:g123.f:k456.b:y1990"""
        parts = theme_id.replace("watchly.theme.", "").split(".")
        anchors, flavors, fallbacks = {}, {}, {}

        roles = {"a": anchors, "f": flavors, "b": fallbacks}

        for idx, part in enumerate(parts):
            if ":" not in part:
                # old format
                if idx == 0:
                    target = anchors
                elif idx == 1:
                    target = flavors
                elif idx == 2:
                    target = fallbacks
                else:
                    continue
                val = part
            else:
                role, val = part.split(":", 1)
                target = roles.get(role)

            if target is None:
                continue

            if val.startswith("g"):
                target["genre"] = val[1:]
            elif val.startswith("k"):
                target["keyword"] = val[1:]
            elif val.startswith("ct"):
                target["country"] = val[2:]
            elif val.startswith("y"):
                target["era"] = val[1:]
            elif val.startswith("r"):
                target["runtime"] = val[1:]
            elif val.startswith("cr"):
                target["creator"] = val[2:]

        return anchors, flavors, fallbacks

    def _axes_to_params(self, axes: dict, content_type: str) -> dict:
        """Convert axes to TMDB discover params."""
        params = {}
        if "genre" in axes:
            params["with_genres"] = axes["genre"].replace("-", "|")
        if "keyword" in axes:
            params["with_keywords"] = axes["keyword"].replace("-", "|")
        if "country" in axes:
            params["with_origin_country"] = axes["country"]
        if "era" in axes:
            try:
                # Value can be single year or range
                val = axes["era"]
                if "-" in val:
                    start_year = int(val.split("-")[0])
                    end_year = int(val.split("-")[1])
                else:
                    start_year = int(val)
                    end_year = start_year + 9

                prefix = "first_air_date" if content_type in ("tv", "series") else "primary_release_date"
                params[f"{prefix}.gte"] = f"{start_year}-01-01"
                params[f"{prefix}.lte"] = f"{end_year}-12-31"
            except Exception:
                logger.error("Failed to parse era axis: {}", axes["era"])
                pass
        if "runtime" in axes:
            bucket = axes["runtime"]
            is_movie = content_type == "movie"
            s_max = RUNTIME_BUCKET_SHORT_MAX_MOVIE if is_movie else RUNTIME_BUCKET_SHORT_MAX_SERIES
            m_max = RUNTIME_BUCKET_MEDIUM_MAX_MOVIE if is_movie else RUNTIME_BUCKET_MEDIUM_MAX_SERIES
            if bucket == "short":
                params["with_runtime.lte"] = s_max
            elif bucket == "medium":
                params["with_runtime.gte"] = s_max
                params["with_runtime.lte"] = m_max
            elif bucket == "long":
                params["with_runtime.gte"] = m_max
        return params

    def _calculate_theme_score(self, item: dict, anchors: dict, flavors: dict, fallbacks: dict) -> float:
        """Calculate weighted score based on axis matches."""
        score = 0.0

        def check_match(axis_name, value):
            if axis_name == "genre":
                item_genres = [str(gid) for gid in item.get("genre_ids", [])]
                target_genres = str(value).split("-")
                return any(tg in item_genres for tg in target_genres)
            if axis_name == "keyword":
                return True  # Optimistic match for discovery items
            if axis_name == "country":
                item_countries = item.get("origin_country", [])
                return value in item_countries
            if axis_name == "era":
                rel = item.get("release_date") or item.get("first_air_date")
                if rel:
                    try:
                        y = int(rel[:4])
                        if "-" in value:
                            start, end = map(int, value.split("-"))
                        else:
                            start = int(value)
                            end = start + 9
                        return start <= y <= end
                    except Exception:
                        logger.error("Failed to parse era axis: {}", value)
                        pass
            if axis_name == "runtime":
                # Runtimes are hard to match exactly from discover results without metadata enrichment
                return True
            return False

        total_anchors = len(anchors)
        matched_anchors = 0
        for name, val in anchors.items():
            if check_match(name, val):
                score += 1.0
                matched_anchors += 1

        # Perfect Match Bonus: Significant boost for items satisfying all anchors
        if total_anchors > 1 and matched_anchors == total_anchors:
            score += 2.0
        elif total_anchors > 0:
            # Proportion boost to differentiate partial matches
            score += (matched_anchors / total_anchors) * 0.5

        for name, val in flavors.items():
            if check_match(name, val):
                score += 0.7
        for name, val in fallbacks.items():
            if check_match(name, val):
                score += 0.3

        return score

    async def _expand_search(self, content_type: str, params: dict, anchors: dict, flavors: dict) -> list[dict]:
        """Expansion logic if results are sparse."""
        # 1. Relax Keyword: Remove keyword constraint
        if "with_keywords" in params:
            new_params = params.copy()
            del new_params["with_keywords"]
            return await self._fetch_discover_candidates(content_type, new_params, pages=[1, 2])

        # 2. Widen Era: remove era constraint
        prefix = "first_air_date" if content_type in ("tv", "series") else "primary_release_date"
        if f"{prefix}.gte" in params:
            new_params = params.copy()
            del new_params[f"{prefix}.gte"]
            del new_params[f"{prefix}.lte"]
            return await self._fetch_discover_candidates(content_type, new_params, pages=[1, 2])

        return []

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

        # Apply global user filters (year range, popularity)
        params = apply_discover_filters(params, self.user_settings)

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
