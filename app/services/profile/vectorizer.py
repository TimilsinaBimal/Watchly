from typing import Any


class ProfileVectorizer:
    """
    Handles tokenization and conversion of TMDB metadata into sparse vectors.
    """

    STOPWORDS = {
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
    def normalize_token(tok: str) -> str:
        """Lowercases, removes non-alphanumeric, and performs lightweight stemming."""
        t = tok.lower()
        t = "".join(ch for ch in t if ch.isalnum())
        if len(t) <= 2:
            return ""

        # Lightweight stemming
        for suf in ("ing", "ers", "ies", "ment", "tion", "s", "ed"):
            if t.endswith(suf) and len(t) - len(suf) >= 3:
                t = t[: -len(suf)]
                break
        return t

    @classmethod
    def tokenize(cls, text: str) -> list[str]:
        """Split text into normalized tokens, removing stopwords and duplicates."""
        if not text:
            return []

        raw = text.replace("-", " ").replace("_", " ")
        tokens = []
        for part in raw.split():
            t = cls.normalize_token(part)
            if not t or t in cls.STOPWORDS:
                continue
            tokens.append(t)

        # De-duplicate while preserving order
        seen = set()
        dedup = []
        for t in tokens:
            if t not in seen:
                seen.add(t)
                dedup.append(t)
        return dedup

    @classmethod
    def vectorize_item(cls, meta: dict[str, Any]) -> dict[str, Any]:
        """
        Converts raw TMDB metadata into a sparse vector format.
        """
        if not meta or not isinstance(meta, dict):
            return {}

        # 1. Robust Keyword Extraction (Movies use 'keywords', TV uses 'results' key)
        keywords_obj = meta.get("keywords")
        raw_keywords = []
        if isinstance(keywords_obj, dict):
            raw_keywords = keywords_obj.get("keywords") or keywords_obj.get("results") or []
        elif isinstance(keywords_obj, list):
            raw_keywords = keywords_obj

        # 2. Extract countries
        countries = []
        prod_countries = meta.get("production_countries")
        if isinstance(prod_countries, list):
            countries = [c.get("iso_3166_1") for c in prod_countries if isinstance(c, dict) and c.get("iso_3166_1")]

        if not countries:
            origin = meta.get("origin_country")
            if isinstance(origin, list):
                countries = origin
            elif isinstance(origin, str):
                countries = [origin]

        # 3. Genres
        genre_ids = meta.get("genre_ids") or []
        if not genre_ids:
            genres_src = meta.get("genres")
            if isinstance(genres_src, list):
                genre_ids = [g.get("id") for g in genres_src if isinstance(g, dict) and g.get("id") is not None]

        # 4. Topics (Title + Overview + Keyword Names)
        title_text = meta.get("name") or meta.get("title") or meta.get("original_title") or ""
        overview_text = meta.get("description") or meta.get("overview") or ""

        kw_names = []
        if isinstance(raw_keywords, list):
            kw_names = [k.get("name") for k in raw_keywords if isinstance(k, dict) and k.get("name")]

        topics_tokens: list[str] = []
        if title_text:
            topics_tokens.extend(cls.tokenize(title_text))
        if overview_text:
            topics_tokens.extend(cls.tokenize(overview_text))
        for nm in kw_names:
            topics_tokens.extend(cls.tokenize(nm))

        # 5. Build Final Vector
        credits = meta.get("credits") or {}
        cast = credits.get("cast") or []
        crew = credits.get("crew") or []

        vector = {
            "genres": [int(g) for g in genre_ids if g is not None],
            "keywords": [int(k["id"]) for k in raw_keywords if isinstance(k, dict) and k.get("id") is not None],
            "cast": [int(c["id"]) for c in cast[:5] if isinstance(c, dict) and c.get("id") is not None],
            "crew": [int(c["id"]) for c in crew if isinstance(c, dict) and c.get("job") == "Director"],
            "year": None,
            "countries": countries,
            "topics": topics_tokens,
        }

        # Year Bucket (Decades)
        date_str = meta.get("release_date") or meta.get("first_air_date")
        if date_str and isinstance(date_str, str):
            try:
                year = int(date_str[:4])
                vector["year"] = (year // 10) * 10
            except (ValueError, TypeError):
                pass

        return vector
