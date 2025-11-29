from collections import defaultdict

from app.models.profile import UserTasteProfile
from app.models.scoring import ScoredItem
from app.services.tmdb_service import TMDBService


class UserProfileService:
    """
    Service to build a User Taste Profile using Sparse Vectors.

    It converts user's watched/loved items into high-dimensional sparse vectors
    based on metadata (genres, keywords, cast, crew) and aggregates them into
    a single 'User Vector' representing their taste.
    """

    def __init__(self):
        self.tmdb_service = TMDBService()

    async def build_user_profile(
        self, scored_items: list[ScoredItem], content_type: str | None = None
    ) -> UserTasteProfile:
        """
        Aggregates multiple item vectors into a single User Taste Profile.
        Optionally filters by content_type (movie/series) to build specific profiles.
        """
        # Use internal dicts for aggregation first, then convert to Pydantic
        profile_data = {
            "genres": defaultdict(float),
            "keywords": defaultdict(float),
            "cast": defaultdict(float),
            "crew": defaultdict(float),
            "years": defaultdict(float),
            "countries": defaultdict(float),
        }

        for item in scored_items:
            # Filter by content type if specified
            if content_type and item.item.type != content_type:
                continue

            # Resolve ID
            tmdb_id = await self._resolve_tmdb_id(item.item.id)
            if not tmdb_id:
                continue

            # Fetch full details including keywords and credits
            meta = await self._fetch_full_metadata(tmdb_id, item.item.type)
            if not meta:
                continue

            # Vectorize this single item
            item_vector = self._vectorize_item(meta)

            # Weighted Aggregation
            # Scale by Interest Score (0.0 - 1.0)
            interest_weight = item.score / 100.0

            self._merge_vector(profile_data, item_vector, interest_weight)

        # Convert to Pydantic Model
        profile = UserTasteProfile(
            genres={"values": dict(profile_data["genres"])},
            keywords={"values": dict(profile_data["keywords"])},
            cast={"values": dict(profile_data["cast"])},
            crew={"values": dict(profile_data["crew"])},
            years={"values": dict(profile_data["years"])},
            countries={"values": dict(profile_data["countries"])},
        )

        # Normalize all vectors to 0-1 range
        profile.normalize_all()

        return profile

    def calculate_similarity(self, profile: UserTasteProfile, item_meta: dict) -> float:
        """
        Calculate the match score between a candidate item and the user profile.
        Uses a weighted dot product strategy.
        """
        # 1. Vectorize the candidate item
        item_vector = self._vectorize_item(item_meta)

        score = 0.0

        # 2. Calculate Dot Product for each dimension
        # We can tune the weights of dimensions here too if needed

        # Genres match
        for g_id in item_vector["genres"]:
            score += profile.genres.values.get(g_id, 0.0) * 1.0

        # Keywords match (Higher weight usually)
        for k_id in item_vector["keywords"]:
            score += profile.keywords.values.get(k_id, 0.0) * 1.5

        # Cast match
        for c_id in item_vector["cast"]:
            score += profile.cast.values.get(c_id, 0.0) * 0.8

        # Crew/Director match
        for cr_id in item_vector["crew"]:
            score += profile.crew.values.get(cr_id, 0.0) * 2.0

        # Year match (Bucket)
        year = item_vector["year"]
        if year:
            score += profile.years.values.get(year, 0.0) * 0.5

        # Country match
        for c_code in item_vector["countries"]:
            score += profile.countries.values.get(c_code, 0.0) * 0.5

        return score

    def _vectorize_item(self, meta: dict) -> dict[str, list[int] | int | list[str] | None]:
        """
        Converts raw TMDB metadata into a sparse vector format.
        Returns lists of IDs or values.
        """
        # extract keywords
        keywords = meta.get("keywords", {}).get("keywords", [])
        if not keywords:
            keywords = meta.get("keywords", {}).get("results", [])

        # extract countries (origin_country is list of strings like ["US", "GB"])
        # In details response, it might be production_countries list of dicts
        countries = []
        if "production_countries" in meta:
            countries = [c.get("iso_3166_1") for c in meta.get("production_countries", []) if c.get("iso_3166_1")]
        elif "origin_country" in meta:
            countries = meta.get("origin_country", [])

        vector = {
            "genres": [g["id"] for g in meta.get("genres", [])],
            "keywords": [k["id"] for k in keywords],
            "cast": [],
            "crew": [],
            "year": None,
            "countries": countries,
        }

        # Cast (Top 3 only to reduce noise)
        cast = meta.get("credits", {}).get("cast", [])
        if not cast:
            pass

        vector["cast"] = [c["id"] for c in cast[:3]]

        # Crew (Directors only)
        crew = meta.get("credits", {}).get("crew", [])
        vector["crew"] = [c["id"] for c in crew if c["job"] == "Director"]

        # Year Bucket (Decades: 2010, 2020, etc.)
        date_str = meta.get("release_date") or meta.get("first_air_date")
        if date_str:
            try:
                year = int(date_str[:4])
                vector["year"] = (year // 10) * 10
            except (ValueError, TypeError):
                pass

        return vector

    def _merge_vector(self, profile: dict, item_vector: dict, weight: float):
        """Merges an item's sparse vector into the main profile with a weight."""

        # Weights for specific dimensions (Feature Importance)
        DIM_WEIGHTS = {"genres": 1.0, "keywords": 1.5, "cast": 0.8, "crew": 2.0, "year": 0.5, "countries": 0.5}

        for dim, ids in item_vector.items():
            dim_weight = DIM_WEIGHTS.get(dim, 1.0)
            final_weight = weight * dim_weight

            if dim == "year":
                if ids is not None:  # ids is a single int for year
                    profile["years"][ids] += final_weight
            elif ids:
                for feature_id in ids:
                    profile[dim][feature_id] += final_weight

    async def _fetch_full_metadata(self, tmdb_id: int, type_: str) -> dict | None:
        """Helper to fetch deep metadata."""
        try:
            if type_ == "movie":
                return await self.tmdb_service.get_movie_details(tmdb_id)
            else:
                return await self.tmdb_service.get_tv_details(tmdb_id)
        except Exception:
            return None

    async def _resolve_tmdb_id(self, stremio_id: str) -> int | None:
        """Resolve Stremio ID (tt... or tmdb:...) to TMDB ID."""
        if stremio_id.startswith("tmdb:"):
            try:
                return int(stremio_id.split(":")[1])
            except (ValueError, IndexError):
                return None

        if stremio_id.startswith("tt"):
            tmdb_id, _ = await self.tmdb_service.find_by_imdb_id(stremio_id)
            return tmdb_id

        return None
