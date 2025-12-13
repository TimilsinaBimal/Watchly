import asyncio
from collections import defaultdict

from app.models.profile import UserTasteProfile
from app.models.scoring import ScoredItem
from app.services.tmdb_service import get_tmdb_service

# TODO: Make these weights dynamic based on user's preferences.
GENRES_WEIGHT = 0.20
KEYWORDS_WEIGHT = 0.30
CAST_WEIGHT = 0.12
CREW_WEIGHT = 0.08
YEAR_WEIGHT = 0.05
COUNTRIES_WEIGHT = 0.05
BASE_GENRE_WEIGHT = 0.05
TOPICS_WEIGHT = 0.20

# Global constant to control size of user's top-genre whitelist used in filtering
TOP_GENRE_WHITELIST_LIMIT = 5


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

    def __init__(self, language: str = "en-US"):
        self.tmdb_service = get_tmdb_service(language=language)

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
            "topics": defaultdict(float),
        }

        async def _process(item):
            # Filter by content type if specified
            if content_type and item.item.type != content_type:
                return None

            # Resolve ID
            tmdb_id = await self._resolve_tmdb_id(item.item.id)
            if not tmdb_id:
                return None

            # Fetch full details including keywords and credits
            meta = await self._fetch_full_metadata(tmdb_id, item.item.type)
            if not meta:
                return None

            # Vectorize this single item
            item_vector = self._vectorize_item(meta)

            # Scale by Interest Score (0.0 - 1.0)
            interest_weight = item.score / 100.0

            return item_vector, interest_weight

        # Launch all item processing coroutines in parallel
        tasks = [_process(item) for item in scored_items]
        results = await asyncio.gather(*tasks)

        # Merge results sequentially to avoid interleaved writes
        for res in results:
            if res is None:
                continue
            item_vector, interest_weight = res
            self._merge_vector(profile_data, item_vector, interest_weight, excluded_genres)

        # Convert to Pydantic Model
        profile = UserTasteProfile(
            genres={"values": dict(profile_data["genres"])},
            keywords={"values": dict(profile_data["keywords"])},
            cast={"values": dict(profile_data["cast"])},
            crew={"values": dict(profile_data["crew"])},
            years={"values": dict(profile_data["years"])},
            countries={"values": dict(profile_data["countries"])},
            topics={"values": dict(profile_data["topics"])},
        )

        # Normalize all vectors to 0-1 range
        profile.normalize_all()

        return profile

    def calculate_similarity(self, profile: UserTasteProfile, item_meta: dict) -> float:
        """
        Final improved similarity scoring function.
        Simplified similarity: linear weighted sum across core dimensions.
        """
        item_vec = self._vectorize_item(item_meta)

        # Linear weighted sum across selected dimensions
        # For each dimension we average per-feature match to avoid bias from many features
        def avg_pref(features, mapping):
            if not features:
                return 0.0
            s = 0.0
            for f in features:
                s += mapping.get(f, 0.0)
            return s / max(1, len(features))

        g_score = avg_pref(item_vec.get("genres", []), profile.genres.values) * GENRES_WEIGHT
        k_score = avg_pref(item_vec.get("keywords", []), profile.keywords.values) * KEYWORDS_WEIGHT
        c_score = avg_pref(item_vec.get("cast", []), profile.cast.values) * CAST_WEIGHT
        t_score = avg_pref(item_vec.get("topics", []), profile.topics.values) * TOPICS_WEIGHT

        # Optional extras with small weights
        crew_score = avg_pref(item_vec.get("crew", []), profile.crew.values) * CREW_WEIGHT
        country_score = avg_pref(item_vec.get("countries", []), profile.countries.values) * COUNTRIES_WEIGHT
        year_val = item_vec.get("year")
        year_score = 0.0
        if year_val is not None:
            year_score = profile.years.values.get(year_val, 0.0) * YEAR_WEIGHT

        score = g_score + k_score + c_score + t_score + crew_score + country_score + year_score

        return float(score)

    def calculate_similarity_with_breakdown(self, profile: UserTasteProfile, item_meta: dict) -> tuple[float, dict]:
        """
        Compute similarity and also return a per-dimension breakdown for logging/tuning.
        Returns (score, breakdown_dict)
        """
        item_vec = self._vectorize_item(item_meta)

        def avg_pref(features, mapping):
            if not features:
                return 0.0
            s = 0.0
            for f in features:
                s += mapping.get(f, 0.0)
            return s / max(1, len(features))

        g_score = avg_pref(item_vec.get("genres", []), profile.genres.values) * GENRES_WEIGHT
        k_score = avg_pref(item_vec.get("keywords", []), profile.keywords.values) * KEYWORDS_WEIGHT
        c_score = avg_pref(item_vec.get("cast", []), profile.cast.values) * CAST_WEIGHT
        t_score = avg_pref(item_vec.get("topics", []), profile.topics.values) * TOPICS_WEIGHT
        crew_score = avg_pref(item_vec.get("crew", []), profile.crew.values) * CREW_WEIGHT
        country_score = avg_pref(item_vec.get("countries", []), profile.countries.values) * COUNTRIES_WEIGHT
        year_val = item_vec.get("year")
        year_score = 0.0
        if year_val is not None:
            year_score = profile.years.values.get(year_val, 0.0) * YEAR_WEIGHT

        score = g_score + k_score + c_score + t_score + crew_score + country_score + year_score

        breakdown = {
            "genres": float(g_score),
            "keywords": float(k_score),
            "cast": float(c_score),
            "topics": float(t_score),
            "crew": float(crew_score),
            "countries": float(country_score),
            "year": float(year_score),
            "total": float(score),
        }

        return float(score), breakdown

    # ---------------- Super-simple overlap similarity ----------------
    @staticmethod
    def _jaccard(a: set, b: set) -> float:
        if not a and not b:
            return 0.0
        if not a or not b:
            return 0.0
        inter = len(a & b)
        union = len(a | b)
        if union == 0:
            return 0.0
        return inter / union

    def calculate_simple_overlap_with_breakdown(
        self,
        profile: UserTasteProfile,
        item_meta: dict,
        *,
        top_topic_tokens: int = 300,
        top_genres: int = 20,
        top_keyword_ids: int = 200,
    ) -> tuple[float, dict]:
        """
        Very simple, explainable similarity using plain set overlaps:
        - Jaccard of token-level "topics" (title/overview/keyword-names tokens)
        - Jaccard of genre ids
        - Jaccard of TMDB keyword ids (optional, small weight)

        No embeddings; robust to partial-word matching via lightweight tokenization
        and heuristic stemming in _tokenize().
        """
        # Preference sets from profile (take top-N by weight to reduce noise)
        pref_topics_sorted = sorted(profile.topics.values.items(), key=lambda kv: kv[1], reverse=True)
        pref_topic_tokens = {k for k, _ in pref_topics_sorted[:top_topic_tokens]}

        pref_genres_sorted = sorted(profile.genres.values.items(), key=lambda kv: kv[1], reverse=True)
        pref_genres = {int(k) for k, _ in pref_genres_sorted[:top_genres]}

        pref_keywords_sorted = sorted(profile.keywords.values.items(), key=lambda kv: kv[1], reverse=True)
        pref_keyword_ids = {int(k) for k, _ in pref_keywords_sorted[:top_keyword_ids]}

        # Item sets
        vec = self._vectorize_item(item_meta)
        item_topic_tokens = set(vec.get("topics") or [])
        item_genres = {int(g) for g in (vec.get("genres") or [])}
        item_keyword_ids = {int(k) for k in (vec.get("keywords") or [])}

        # Jaccard components
        topics_j = self._jaccard(item_topic_tokens, pref_topic_tokens)
        genres_j = self._jaccard(item_genres, pref_genres)
        kw_j = self._jaccard(item_keyword_ids, pref_keyword_ids)

        # Simple weighted sum; emphasize token overlap
        w_topics, w_genres, w_kw = 0.6, 0.25, 0.15
        score = (topics_j * w_topics) + (genres_j * w_genres) + (kw_j * w_kw)

        breakdown = {
            "topics_jaccard": float(topics_j),
            "genres_jaccard": float(genres_j),
            "keywords_jaccard": float(kw_j),
            "total": float(score),
        }

        return float(score), breakdown

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

        # genres: prefer explicit genre_ids; fallback to dict list if present
        genre_ids = meta.get("genre_ids") or []
        if not genre_ids:
            genres_src = meta.get("genres") or []
            if genres_src and isinstance(genres_src, list) and genres_src and isinstance(genres_src[0], dict):
                genre_ids = [g.get("id") for g in genres_src if isinstance(g, dict) and g.get("id") is not None]

        # Build topics tokens from title/overview and keyword names
        # Handle both our enriched meta format and raw TMDB payloads
        title_text = meta.get("name") or meta.get("title") or meta.get("original_title") or ""
        overview_text = meta.get("description") or meta.get("overview") or ""
        kw_names = [k.get("name") for k in keywords if isinstance(k, dict) and k.get("name")]
        topics_tokens: list[str] = []
        topics_tokens.extend(self._tokenize(title_text))
        topics_tokens.extend(self._tokenize(overview_text))
        for nm in kw_names:
            topics_tokens.extend(self._tokenize(nm))

        vector = {
            "genres": genre_ids,
            "keywords": [k["id"] for k in keywords],
            "cast": [],
            "crew": [],
            "year": None,
            "countries": countries,
            "topics": topics_tokens,
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
            "topics": TOPICS_WEIGHT,
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

    # ---------------- Tokenization helpers ----------------
    _STOPWORDS = {
        "a",
        "an",
        "and",
        "the",
        "of",
        "to",
        "in",
        "on",
        "for",
        "with",
        "by",
        "from",
        "at",
        "as",
        "is",
        "it",
        "this",
        "that",
        "be",
        "or",
        "are",
        "was",
        "were",
        "has",
        "have",
        "had",
        "into",
        "their",
        "his",
        "her",
        "its",
        "but",
        "not",
        "no",
        "so",
        "about",
        "over",
        "under",
        "after",
        "before",
        "than",
        "then",
        "out",
        "up",
        "down",
        "off",
        "only",
        "more",
        "most",
        "some",
        "any",
    }

    @staticmethod
    def _normalize_token(tok: str) -> str:
        t = tok.lower()
        t = "".join(ch for ch in t if ch.isalnum())
        if len(t) <= 2:
            return ""
        for suf in ("ing", "ers", "ies", "ment", "tion", "s", "ed"):
            if t.endswith(suf) and len(t) - len(suf) >= 3:
                t = t[: -len(suf)]
                break
        return t

    def _tokenize(self, text: str) -> list[str]:
        if not text:
            return []
        raw = text.replace("-", " ").replace("_", " ")
        tokens = []
        for part in raw.split():
            t = self._normalize_token(part)
            if not t or t in self._STOPWORDS:
                continue
            tokens.append(t)
        # de-duplicate while preserving order
        seen = set()
        dedup = []
        for t in tokens:
            if t in seen:
                continue
            seen.add(t)
            dedup.append(t)
        return dedup

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
