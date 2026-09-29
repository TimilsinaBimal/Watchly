import asyncio
from typing import Any

from loguru import logger

from app.core.settings import UserSettings
from app.models.profile import TasteProfile
from app.services.profile.constants import (
    RUNTIME_BUCKET_MEDIUM_MAX_MOVIE,
    RUNTIME_BUCKET_MEDIUM_MAX_SERIES,
    RUNTIME_BUCKET_SHORT_MAX_MOVIE,
    RUNTIME_BUCKET_SHORT_MAX_SERIES,
)
from app.services.profile.scorer import ProfileScorer
from app.services.recommendation.filtering import RecommendationFiltering, apply_discover_filters
from app.services.recommendation.scoring import RecommendationScoring
from app.services.recommendation.utils import content_type_to_mtype
from app.services.tmdb.service import TMDBService


class ThemeBasedService:
    """Theme rows from role-based axis recipes: anchors (a), flavors (f) and fallbacks (b),
    weighted 1.0 / 0.7 / 0.3 when scoring a candidate against the theme."""

    def __init__(self, tmdb_service: TMDBService, user_settings: UserSettings):
        self.tmdb_service = tmdb_service
        self.user_settings = user_settings
        self.scorer = ProfileScorer()

    async def get_recommendations_for_theme(
        self,
        theme_id: str,
        content_type: str,
        profile: TasteProfile | None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        anchors, flavors, fallbacks = self._parse_theme_id(theme_id)
        excluded_ids = RecommendationFiltering.get_excluded_genre_ids(self.user_settings, content_type)

        # Country and era constrain every query, whichever role they came in as.
        all_constraints = {**anchors, **flavors, **fallbacks}
        mandatory_filters = {}
        if "country" in all_constraints:
            mandatory_filters["country"] = all_constraints["country"]
        if "era" in all_constraints:
            mandatory_filters["era"] = all_constraints["era"]

        logger.debug(f"Theme discovery for {theme_id}: anchors={anchors}, flavors={flavors}, fallbacks={fallbacks}")

        fetch_tasks = []
        if all_constraints:
            combined_params = self._axes_to_params(all_constraints, content_type)
            if excluded_ids:
                with_ids = {int(g) for g in combined_params.get("with_genres", "").split("|") if g}
                without = [g for g in excluded_ids if g not in with_ids]
                if without:
                    combined_params["without_genres"] = "|".join(str(g) for g in without)
            fetch_tasks.append(self._fetch_discover_candidates(content_type, combined_params, pages=[1, 2, 3]))

        results = await asyncio.gather(*fetch_tasks, return_exceptions=True)
        candidates = []
        for res in results:
            if isinstance(res, Exception):
                logger.debug(f"Error fetching combined: {type(res).__name__}")
                continue
            if isinstance(res, list):
                for item in res:
                    item["_discovery_tier"] = "combined"
                candidates.extend(res)

        logger.debug(f"Phase 1 (combined): {len(candidates)} candidates")

        # Sparse: query each axis on its own, still under the country/era constraints.
        if len(candidates) < limit * 2:
            fetch_tasks = []
            for axis_name, axis_value in all_constraints.items():
                params = self._axes_to_params({axis_name: axis_value}, content_type)
                for filter_name, filter_value in mandatory_filters.items():
                    if filter_name != axis_name:
                        params.update(self._axes_to_params({filter_name: filter_value}, content_type))

                if excluded_ids:
                    with_ids = {int(g) for g in params.get("with_genres", "").split("|") if g}
                    without = [g for g in excluded_ids if g not in with_ids]
                    if without:
                        params["without_genres"] = "|".join(str(g) for g in without)

                fetch_tasks.append(self._fetch_discover_candidates(content_type, params, pages=[1, 2]))

            results = await asyncio.gather(*fetch_tasks, return_exceptions=True)
            for res in results:
                if isinstance(res, Exception):
                    logger.debug(f"Error fetching individual: {type(res).__name__}")
                    continue
                if isinstance(res, list):
                    for item in res:
                        item["_discovery_tier"] = "individual"
                    candidates.extend(res)

            logger.debug(f"Phase 2 (individual): Total {len(candidates)} candidates")

        # Still sparse: drop the keyword constraint from the primary anchor.
        if len(candidates) < limit and anchors:
            primary_axis = dict([next(iter(anchors.items()))])
            base_p = self._axes_to_params(primary_axis, content_type)
            if "with_keywords" in base_p:
                del base_p["with_keywords"]
                expanded = await self._fetch_discover_candidates(content_type, base_p, pages=[1, 2])
                for item in expanded:
                    item["_discovery_tier"] = "expanded"
                candidates.extend(expanded)

        scored = []
        mtype = content_type_to_mtype(content_type)

        for item in candidates:
            theme_match = self._calculate_theme_score(item, anchors, flavors, fallbacks)

            if profile:
                base_score = RecommendationScoring.calculate_final_score(
                    item=item,
                    profile=profile,
                    scorer=self.scorer,
                    mtype=mtype,
                )
            else:
                base_score = RecommendationScoring.normalize(item.get("vote_average", 0))

            # Combine: theme match is the primary sorter for catalog rows
            final_score = (theme_match * 0.7) + (base_score * 0.3)

            # Apply tier multiplier
            tier = item.get("_discovery_tier", "individual")
            if tier == "combined":
                final_score *= 2.0  # Boost combined matches to appear first

            scored.append((final_score, item))

        scored.sort(key=lambda x: x[0], reverse=True)
        unique_results = []
        seen = set()
        for _, item in scored:
            if item["id"] not in seen:
                unique_results.append(item)
                seen.add(item["id"])
            if len(unique_results) >= limit * 2:
                break
        return unique_results

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
                logger.warning(f"Failed to parse era axis: {axes['era']}")
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
                        logger.warning(f"Failed to parse era axis: {value}")
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

    async def _fetch_discover_candidates(
        self, content_type: str, params: dict[str, Any], pages: list[int]
    ) -> list[dict[str, Any]]:
        candidates = []
        params = apply_discover_filters(params, self.user_settings)

        tasks = [self.tmdb_service.get_discover(content_type, page=p, **params) for p in pages]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for res in results:
            if isinstance(res, Exception):
                logger.debug(f"Error fetching discover: {type(res).__name__}")
                continue
            candidates.extend(res.get("results", []))

        return candidates
