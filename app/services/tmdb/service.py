import functools
from typing import Any

from async_lru import alru_cache
from loguru import logger

from app.services.tmdb.client import TMDBClient

# from app.services.profile.constants import TOP_PICKS_MIN_VOTE_COUNT, TOP_PICKS_MIN_RATING


class TMDBService:
    """
    Service for interacting with The Movie Database (TMDB) API.
    Refactored to use TMDBClient for better resilience and maintainability.
    """

    def __init__(self, api_key: str, language: str = "en-US"):
        self.client = TMDBClient(api_key=api_key, language=language)

    async def close(self):
        """Close the underlying HTTP client."""
        await self.client.close()

    @alru_cache(maxsize=1000)
    async def find_by_imdb_id(self, imdb_id: str) -> tuple[int | None, str | None]:
        """Find TMDB ID and type by IMDB ID."""
        try:
            params = {"external_source": "imdb_id"}
            data = await self.client.get(f"/find/{imdb_id}", params=params)

            if not data or not isinstance(data, dict):
                return None, None

            # Check movie results
            movie_results = data.get("movie_results", [])
            if movie_results:
                tmdb_id = movie_results[0].get("id")
                if tmdb_id:
                    return tmdb_id, "movie"

            # Check TV results
            tv_results = data.get("tv_results", [])
            if tv_results:
                tmdb_id = tv_results[0].get("id")
                if tmdb_id:
                    return tmdb_id, "tv"

            return None, None
        except Exception as e:
            logger.exception(f"Error finding TMDB ID for IMDB {imdb_id}: {e}")
            return None, None

    @alru_cache(maxsize=500, ttl=86400)
    async def get_movie_details(self, movie_id: int) -> dict[str, Any]:
        """Get details of a specific movie with credits and keywords."""
        params = {"append_to_response": "credits,external_ids,keywords"}
        return await self.client.get(f"/movie/{movie_id}", params=params)

    @alru_cache(maxsize=500, ttl=86400)
    async def get_tv_details(self, tv_id: int) -> dict[str, Any]:
        """Get details of a specific TV series with credits and keywords."""
        params = {"append_to_response": "credits,external_ids,keywords"}
        return await self.client.get(f"/tv/{tv_id}", params=params)

    @alru_cache(maxsize=500, ttl=86400)
    async def get_recommendations(self, tmdb_id: int, media_type: str, page: int = 1) -> dict[str, Any]:
        """Get recommendations based on TMDB ID and media type."""
        params = {"page": page}
        return await self.client.get(f"/{media_type}/{tmdb_id}/recommendations", params=params)

    @alru_cache(maxsize=500, ttl=86400)
    async def get_similar(self, tmdb_id: int, media_type: str, page: int = 1) -> dict[str, Any]:
        """Get similar content based on TMDB ID and media type."""
        params = {"page": page}
        return await self.client.get(f"/{media_type}/{tmdb_id}/similar", params=params)

    async def get_discover(
        self,
        media_type: str,
        with_genres: str | None = None,
        sort_by: str = "popularity.desc",
        page: int = 1,
        **kwargs,
    ) -> dict[str, Any]:
        """Get discover content based on params."""
        mt = "movie" if media_type == "movie" else "tv"
        params = {"page": page, "sort_by": sort_by}
        if with_genres:
            params["with_genres"] = with_genres
        # # always filter by vote count
        # params["vote_count.gte"] = TOP_PICKS_MIN_VOTE_COUNT
        # params["vote_average.gte"] = TOP_PICKS_MIN_RATING
        params.update(kwargs)
        return await self.client.get(f"/discover/{mt}", params=params)

    @alru_cache(maxsize=1000)
    async def get_keyword_details(self, keyword_id: int) -> dict[str, Any]:
        """Get details of a specific keyword."""
        return await self.client.get(f"/keyword/{keyword_id}")

    @alru_cache(maxsize=500, ttl=86400)
    async def search_keywords(self, query: str, page: int = 1) -> dict[str, Any]:
        """Search keywords by name. Returns { results: [ { id, name } ], ... }."""
        if not (query or str(query).strip()):
            return {"results": []}
        return await self.client.get("/search/keyword", params={"query": str(query).strip(), "page": page})

    @alru_cache(maxsize=500, ttl=86400)
    async def get_person_details(self, person_id: int) -> dict[str, Any]:
        """Get details of a specific person (actor/director)."""
        return await self.client.get(f"/person/{person_id}")

    async def get_trending(self, media_type: str, time_window: str = "week", page: int = 1) -> dict[str, Any]:
        """Get trending content."""
        mt = "movie" if media_type == "movie" else "tv"
        params = {"page": page}
        return await self.client.get(f"/trending/{mt}/{time_window}", params=params)

    async def get_top_rated(self, media_type: str, page: int = 1) -> dict[str, Any]:
        """Get top-rated content list."""
        mt = "movie" if media_type == "movie" else "tv"
        params = {"page": page}
        return await self.client.get(f"/{mt}/top_rated", params=params)

    @alru_cache(maxsize=1, ttl=86400)
    async def get_languages(self) -> list[dict[str, Any]]:
        """Fetch supported languages from TMDB."""
        return await self.client.get("/configuration/languages")

    @alru_cache(maxsize=1, ttl=86400)
    async def get_countries(self) -> list[dict[str, Any]]:
        """Fetch supported countries from TMDB."""
        return await self.client.get("/configuration/countries")

    @alru_cache(maxsize=1, ttl=86400)
    async def get_primary_translations(self) -> list[str]:
        """Fetch supported primary translations from TMDB."""
        return await self.client.get("/configuration/primary_translations")

    @alru_cache(maxsize=2000, ttl=86400)
    async def get_images(
        self, media_type: str, tmdb_id: int, include_image_language: str = "en,fr,null"
    ) -> dict[str, Any]:
        """
        Fetch images (posters, logos, backdrops) for a movie or TV show.
        include_image_language: comma-separated iso_639_1 codes + "null" for language-less images.
        """
        if media_type not in ("movie", "tv"):
            return {}
        path = f"/{media_type}/{tmdb_id}/images"
        params = {"include_image_language": include_image_language}
        return await self.client.get(path, params=params)

    @staticmethod
    def _score_image(img: dict[str, Any]) -> tuple[float, int]:
        """Higher is better (TMDB vote fields)."""
        va = img.get("vote_average")
        vc = img.get("vote_count")
        try:
            va_f = float(va) if va is not None else 0.0
        except (TypeError, ValueError):
            va_f = 0.0
        try:
            vc_i = int(vc) if vc is not None else 0
        except (TypeError, ValueError):
            vc_i = 0
        return (va_f, vc_i)

    @classmethod
    def _pick_best_in_language_bucket(
        cls,
        images_list: list[dict[str, Any]],
        iso: str | None,
    ) -> str | None:
        """Among images with this iso_639_1 (or None for language-neutral), pick highest-rated."""
        if iso is None:
            candidates = [img for img in images_list if img.get("iso_639_1") in (None, "")]
        else:
            iso_l = iso.lower()
            candidates = [img for img in images_list if (img.get("iso_639_1") or "").lower() == iso_l]
        if not candidates:
            return None
        best = max(candidates, key=cls._score_image)
        path = best.get("file_path")
        return path if path else None

    @classmethod
    def _pick_logo_by_language(
        cls,
        logos: list[dict[str, Any]] | None,
        primary_iso: str,
    ) -> str | None:
        """
        Logo only: exact ISO 639-1 match, else language-neutral (null). No cross-language fallback.

        TMDB tags logos with iso_639_1 only (no region). Falling back to another language (e.g. another
        "fr" market's artwork or "en") often mismatches localized titles; omit logo so Metahub/default applies.
        """
        if not logos:
            return None
        p = (primary_iso or "en").lower()
        if path := cls._pick_best_in_language_bucket(logos, p):
            return path
        return cls._pick_best_in_language_bucket(logos, None)

    @staticmethod
    def _pick_image_by_language(
        images_list: list[dict[str, Any]] | None,
        preferred_lang_codes: list[str | None],
    ) -> str | None:
        """
        Pick best image from list by language preference (same logic as no-stremio-addon).
        preferred_lang_codes: e.g. ["en", None, "fr"] -> prefer en, then no language, then fr.
        """
        if not images_list:
            return None
        for lang in preferred_lang_codes:
            for img in images_list:
                iso = img.get("iso_639_1")
                if iso == lang:
                    path = img.get("file_path")
                    if path:
                        return path
        return images_list[0].get("file_path") if images_list else None

    def _language_to_image_preference(self, language: str) -> tuple[list[str | None], str]:
        """
        Build preferred lang order and include_image_language param from language (e.g. en-US, fr-FR).
        Returns (preferred_lang_codes, include_image_language).
        """
        primary = (language or "en-US").split("-")[0].lower() if language else "en"
        fallbacks = [c for c in ("en", "fr", "null") if c != primary]
        preferred = [primary, None, *[c for c in fallbacks if c != "null"]]
        include = ",".join([primary] + fallbacks)
        return preferred, include

    async def get_images_for_title(
        self,
        media_type: str,
        tmdb_id: int,
        language: str | None = None,
    ) -> dict[str, str]:
        """
        Get poster, logo and background URLs for a title in the requested language.

        Posters/backdrops: requested language, then null, then common fallbacks (same idea as no-stremio-addon).

        Logos: only the exact ISO 639-1 language or a language-neutral (null) asset — no fallback to other
        languages, so we do not show a logo whose text targets another locale when the exact translation
        is missing (e.g. another French market). If neither exists, no logo is returned (callers may use Metahub).
        """
        lang = language or self.client.language
        preferred, include = self._language_to_image_preference(lang)
        data = await self.get_images(media_type, tmdb_id, include_image_language=include)
        if not data:
            return {}

        base_poster_logo = "https://image.tmdb.org/t/p/w500"
        base_backdrop = "https://image.tmdb.org/t/p/w780"

        def to_url(base: str, path: str | None) -> str:
            if not path:
                return ""
            return base + (path if path.startswith("/") else "/" + path)

        posters = data.get("posters") or []
        logos = data.get("logos") or []
        backdrops = data.get("backdrops") or []

        poster_path = self._pick_image_by_language(posters, preferred)
        primary_iso = (lang or "en-US").split("-")[0].lower() if lang else "en"
        logo_path = self._pick_logo_by_language(logos, primary_iso)
        backdrop_path = self._pick_image_by_language(backdrops, preferred)

        result: dict[str, str] = {}
        if poster_path:
            result["poster"] = to_url(base_poster_logo, poster_path)
        if logo_path:
            result["logo"] = to_url(base_poster_logo, logo_path)
        if backdrop_path:
            result["background"] = to_url(base_backdrop, backdrop_path)
        return result


@functools.lru_cache(maxsize=128)
def get_tmdb_service(language: str = "en-US", api_key: str | None = None) -> TMDBService:
    from app.core.config import settings

    key = api_key or settings.TMDB_API_KEY
    if not key:
        raise ValueError("TMDB API key is required (set in settings or TMDB_API_KEY env).")
    return TMDBService(api_key=key, language=language)
