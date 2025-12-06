from collections import defaultdict

from app.models.profile import UserTasteProfile
from app.models.scoring import ScoredItem
from app.services.tmdb_service import TMDBService

# TODO: Make these weights dynamic based on user's preferences.
GENRES_WEIGHT = 0.3
KEYWORDS_WEIGHT = 0.40
CAST_WEIGHT = 0.1
CREW_WEIGHT = 0.1
YEAR_WEIGHT = 0.05
COUNTRIES_WEIGHT = 0.05
BASE_GENRE_WEIGHT = 0.15


def emphasis(x: float) -> float:
    """
    Non-linear boost for strong preferences.
    """
    return x**1.25


def safe_div(a, b):
    return a / b if b else 0.0


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
        self,
        scored_items: list[ScoredItem],
        content_type: str | None = None,
        excluded_genres: list[int] | None = None,
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

            self._merge_vector(profile_data, item_vector, interest_weight, excluded_genres)

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
        Final improved similarity scoring function.
        Uses normalized sparse matching + rarity boosting + non-linear emphasis.
        """

        item_vec = self._vectorize_item(item_meta)

        score = 0.0

        # 1. GENRES
        # Normalize so movies with many genres don't get excessive score.
        for gid in item_vec["genres"]:
            pref = profile.genres.values.get(gid, 0.0)

            if pref > 0:
                s = emphasis(pref)
                s = safe_div(s, len(item_vec["genres"]))
                score += s * GENRES_WEIGHT

            # Soft prior bias (genre-only)
            base_pref = profile.top_genres_normalized.get(gid, 0.0)
            score += base_pref * BASE_GENRE_WEIGHT

        # 2. KEYWORDS
        for kw in item_vec["keywords"]:
            pref = profile.keywords.values.get(kw, 0.0)

            if pref > 0:
                s = emphasis(pref)
                s = safe_div(s, len(item_vec["keywords"]))
                score += s * KEYWORDS_WEIGHT

        # 3. CAST
        for cid in item_vec["cast"]:
            pref = profile.cast.values.get(cid, 0.0)

            if pref > 0:
                s = emphasis(pref)
                s = safe_div(s, len(item_vec["cast"]))
                score += s * CAST_WEIGHT

        # 4. CREW
        for cr in item_vec["crew"]:
            pref = profile.crew.values.get(cr, 0.0)

            if pref > 0:
                s = emphasis(pref)
                s = safe_div(s, len(item_vec["crew"]))
                score += s * CREW_WEIGHT

        # 5. COUNTRIES
        for c in item_vec["countries"]:
            pref = profile.countries.values.get(c, 0.0)

            if pref > 0:
                s = emphasis(pref)
                s = safe_div(s, len(item_vec["countries"]))
                score += s * COUNTRIES_WEIGHT

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

    def _merge_vector(
        self,
        profile: dict,
        item_vector: dict,
        weight: float,
        excluded_genres: list[int] | None = None,
    ):
        """Merges an item's sparse vector into the main profile with a weight."""

        # Weights for specific dimensions (Feature Importance)
        DIM_WEIGHTS = {
            "genres": GENRES_WEIGHT,
            "keywords": KEYWORDS_WEIGHT,
            "cast": CAST_WEIGHT,
            "crew": CREW_WEIGHT,
            "year": YEAR_WEIGHT,
            "countries": COUNTRIES_WEIGHT,
        }

        for dim, ids in item_vector.items():
            dim_weight = DIM_WEIGHTS.get(dim, 1.0)
            final_weight = weight * dim_weight

            if dim == "year":
                if ids is not None:  # ids is a single int for year
                    profile["years"][ids] += final_weight
            elif ids:
                for feature_id in ids:
                    if dim == "genres" and excluded_genres and feature_id in excluded_genres:
                        continue
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
