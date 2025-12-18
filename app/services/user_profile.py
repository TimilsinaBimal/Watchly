import asyncio
from collections import defaultdict

from app.models.profile import UserTasteProfile
from app.models.scoring import ScoredItem
from app.services.tmdb import get_tmdb_service

# Feature Weights
GENRES_WEIGHT = 0.20
KEYWORDS_WEIGHT = 0.30
CAST_WEIGHT = 0.12
CREW_WEIGHT = 0.08
YEAR_WEIGHT = 0.05
COUNTRIES_WEIGHT = 0.05
TOPICS_WEIGHT = 0.20


class Tokenizer:
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

    def tokenize(self, text: str) -> list[str]:
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


class UserProfileService:
    def __init__(self, language: str = "en-US"):
        self.tmdb_service = get_tmdb_service(language=language)
        self.tokenizer = Tokenizer()

    async def build_user_profile(
        self,
        scored_items: list[ScoredItem],
        content_type: str | None = None,
        excluded_genres: list[int] | None = None,
    ) -> UserTasteProfile:
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
            if content_type and item.item.type != content_type:
                return None
            tmdb_id = await self._resolve_tmdb_id(item.item.id)
            if not tmdb_id:
                return None

            meta = await self._fetch_full_metadata(tmdb_id, item.item.type)
            if not meta:
                return None

            item_vector = self._vectorize_item(meta)
            interest_weight = item.score / 100.0
            return item_vector, interest_weight

        tasks = [_process(item) for item in scored_items]
        results = await asyncio.gather(*tasks)

        for res in results:
            if res is None:
                continue
            item_vector, interest_weight = res
            self._merge_vector(profile_data, item_vector, interest_weight, excluded_genres)

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

    def calculate_similarity(self, profile: UserTasteProfile, item_meta: dict) -> float:
        item_vec = self._vectorize_item(item_meta)

        def avg_pref(features, mapping):
            if not features:
                return 0.0
            s = sum(mapping.get(f, 0.0) for f in features)
            return s / max(1, len(features))

        scores = [
            avg_pref(item_vec.get("genres", []), profile.genres.values) * GENRES_WEIGHT,
            avg_pref(item_vec.get("keywords", []), profile.keywords.values) * KEYWORDS_WEIGHT,
            avg_pref(item_vec.get("cast", []), profile.cast.values) * CAST_WEIGHT,
            avg_pref(item_vec.get("topics", []), profile.topics.values) * TOPICS_WEIGHT,
            avg_pref(item_vec.get("crew", []), profile.crew.values) * CREW_WEIGHT,
            avg_pref(item_vec.get("countries", []), profile.countries.values) * COUNTRIES_WEIGHT,
        ]

        year_val = item_vec.get("year")
        if year_val is not None:
            scores.append(profile.years.values.get(year_val, 0.0) * YEAR_WEIGHT)

        return float(sum(scores))

    def _vectorize_item(self, meta: dict) -> dict:
        keywords = meta.get("keywords", {}).get("keywords", []) or meta.get("keywords", {}).get("results", [])

        countries = []
        if "production_countries" in meta:
            countries = [c.get("iso_3166_1") for c in meta.get("production_countries", [])]
        elif "origin_country" in meta:
            countries = meta.get("origin_country", [])

        genre_ids = meta.get("genre_ids") or []
        if not genre_ids:
            genres_src = meta.get("genres") or []
            genre_ids = [g.get("id") for g in genres_src if isinstance(g, dict) and g.get("id")]

        title_text = meta.get("name") or meta.get("title") or meta.get("original_title") or ""
        overview_text = meta.get("description") or meta.get("overview") or ""
        kw_names = [k.get("name") for k in keywords if isinstance(k, dict)]

        topics_tokens = []
        topics_tokens.extend(self.tokenizer.tokenize(title_text))
        topics_tokens.extend(self.tokenizer.tokenize(overview_text))
        for nm in kw_names:
            topics_tokens.extend(self.tokenizer.tokenize(nm))

        vector = {
            "genres": genre_ids,
            "keywords": [k["id"] for k in keywords if isinstance(k, dict)],
            "cast": [],
            "crew": [],
            "year": None,
            "countries": countries,
            "topics": topics_tokens,
        }

        cast = meta.get("credits", {}).get("cast", [])
        vector["cast"] = [c["id"] for c in cast[:3]]

        crew = meta.get("credits", {}).get("crew", [])
        vector["crew"] = [c["id"] for c in crew if c.get("job") == "Director"]

        date_str = meta.get("release_date") or meta.get("first_air_date")
        if date_str:
            try:
                year = int(str(date_str)[:4])
                vector["year"] = (year // 10) * 10
            except (ValueError, TypeError):
                pass

        return vector

    def _merge_vector(self, profile, item_vector, weight, excluded_genres):
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
                if ids is not None:
                    profile["years"][ids] += final_weight
            elif ids:
                for feature_id in ids:
                    if dim == "genres" and excluded_genres and feature_id in excluded_genres:
                        continue
                    profile[dim][feature_id] += final_weight

    async def _fetch_full_metadata(self, tmdb_id: int, type_: str) -> dict | None:
        try:
            if type_ == "movie":
                return await self.tmdb_service.get_movie_details(tmdb_id)
            else:
                return await self.tmdb_service.get_tv_details(tmdb_id)
        except Exception:
            return None

    async def _resolve_tmdb_id(self, stremio_id: str) -> int | None:
        if stremio_id.startswith("tmdb:"):
            try:
                return int(stremio_id.split(":")[1])
            except Exception:
                return None
        if stremio_id.startswith("tt"):
            tmdb_id, _ = await self.tmdb_service.find_by_imdb_id(stremio_id)
            return tmdb_id
        return None
