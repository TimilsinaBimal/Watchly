import asyncio
from collections import defaultdict
from typing import Any

from app.models.profile import UserTasteProfile
from app.models.scoring import ScoredItem
from app.services.profile.similarity import (
    CAST_WEIGHT,
    COUNTRIES_WEIGHT,
    CREW_WEIGHT,
    GENRES_WEIGHT,
    KEYWORDS_WEIGHT,
    TOPICS_WEIGHT,
    YEAR_WEIGHT,
    calculate_similarity_breakdown,
    calculate_simple_overlap_breakdown,
)
from app.services.profile.vectorizer import ProfileVectorizer
from app.services.tmdb_service import get_tmdb_service


class UserProfileService:
    """
    Service for building and managing User Taste Profiles.
    """

    def __init__(self, language: str = "en-US"):
        self.tmdb_service = get_tmdb_service(language=language)

    async def build_user_profile(
        self,
        scored_items: list[ScoredItem],
        content_type: str | None = None,
        excluded_genres: list[int] | None = None,
    ) -> UserTasteProfile:
        """
        Build a comprehensive taste profile from a list of scored items.
        """
        profile_data = {
            "genres": defaultdict(float),
            "keywords": defaultdict(float),
            "cast": defaultdict(float),
            "crew": defaultdict(float),
            "years": defaultdict(float),
            "countries": defaultdict(float),
            "topics": defaultdict(float),
        }

        async def _process_item(item: ScoredItem):
            # 1. Filter by content type (movie/series)
            if content_type and item.item.type != content_type:
                return None

            # 2. Resolve TMDB ID
            tmdb_id = await self._resolve_tmdb_id(item.item.id)
            if not tmdb_id:
                return None

            # 3. Fetch detailed metadata
            meta = await self._fetch_full_metadata(tmdb_id, item.item.type)
            if not meta:
                return None

            # 4. Vectorize item
            item_vector = ProfileVectorizer.vectorize_item(meta)

            # 5. Scale by interest score
            interest_weight = item.score / 100.0

            return item_vector, interest_weight

        # Process all items in parallel
        tasks = [_process_item(item) for item in scored_items]
        results = await asyncio.gather(*tasks)

        # Merge results into the profile
        for res in results:
            if res:
                item_vector, weight = res
                self._merge_vector(profile_data, item_vector, weight, excluded_genres)

        # Build and normalize Pydantic model
        profile = UserTasteProfile(
            genres={"values": dict(profile_data["genres"])},
            keywords={"values": dict(profile_data["keywords"])},
            cast={"values": dict(profile_data["cast"])},
            crew={"values": dict(profile_data["crew"])},
            years={"values": dict(profile_data["years"])},
            countries={"values": dict(profile_data["countries"])},
            topics={"values": dict(profile_data["topics"])},
        )
        profile.normalize_all()
        return profile

    def _merge_vector(
        self,
        profile_data: dict[str, Any],
        item_vector: dict[str, Any],
        weight: float,
        excluded_genres: list[int] | None = None,
    ):
        """Merge an item's vector into the profile with weighted scoring."""
        WEIGHT_MAP = {
            "genres": GENRES_WEIGHT,
            "keywords": KEYWORDS_WEIGHT,
            "cast": CAST_WEIGHT,
            "crew": CREW_WEIGHT,
            "year": YEAR_WEIGHT,
            "countries": COUNTRIES_WEIGHT,
            "topics": TOPICS_WEIGHT,
        }

        for dim, values in item_vector.items():
            dim_weight = WEIGHT_MAP.get(dim, 1.0)
            final_weight = weight * dim_weight

            if dim == "year":
                if values is not None:
                    profile_data["years"][values] += final_weight
            elif values:
                for feature_id in values:
                    if dim == "genres" and excluded_genres and feature_id in excluded_genres:
                        continue
                    profile_data[dim][feature_id] += final_weight

    async def _resolve_tmdb_id(self, stremio_id: str) -> int | None:
        """Resolve various Stremio ID formats to a TMDB integer ID."""
        if stremio_id.startswith("tmdb:"):
            try:
                return int(stremio_id.split(":")[1])
            except (ValueError, IndexError):
                return None

        if stremio_id.startswith("tt"):
            tmdb_id, _ = await self.tmdb_service.find_by_imdb_id(stremio_id)
            return tmdb_id
        return None

    async def _fetch_full_metadata(self, tmdb_id: int, type_: str) -> dict | None:
        """Fetch full metadata from TMDB based on media type."""
        try:
            if type_ == "movie":
                return await self.tmdb_service.get_movie_details(tmdb_id)
            return await self.tmdb_service.get_tv_details(tmdb_id)
        except Exception:
            return None

    def calculate_similarity(self, profile: UserTasteProfile, item_meta: dict) -> float:
        """Get total similarity score between profile and item."""
        score, _ = calculate_similarity_breakdown(profile, item_meta)
        return score

    def calculate_similarity_with_breakdown(self, profile: UserTasteProfile, item_meta: dict) -> tuple[float, dict]:
        """Get similarity score and dimensional breakdown."""
        return calculate_similarity_breakdown(profile, item_meta)

    def calculate_simple_overlap_with_breakdown(
        self, profile: UserTasteProfile, item_meta: dict, **kwargs
    ) -> tuple[float, dict]:
        """Get simple overlap similarity and breakdown."""
        return calculate_simple_overlap_breakdown(profile, item_meta, **kwargs)
