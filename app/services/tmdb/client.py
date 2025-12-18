import asyncio
import functools
import random

import httpx
from async_lru import alru_cache
from loguru import logger

from app.core.config import settings
from app.core.version import __version__


class TMDBClient:
    """Core client for interacting with The Movie Database (TMDB) API."""

    def __init__(self, language: str = "en-US"):
        self.api_key = settings.TMDB_API_KEY
        self.base_url = "https://api.themoviedb.org/3"
        self.language = language
        self._client: httpx.AsyncClient | None = None
        if not self.api_key:
            logger.warning("TMDB_API_KEY is not configured.")

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=10.0,
                limits=httpx.Limits(max_keepalive_connections=20, max_connections=100),
                http2=True,
                headers={
                    "User-Agent": f"Watchly/{__version__}",
                    "Accept": "application/json",
                },
            )
        return self._client

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    async def make_request(self, endpoint: str, params: dict | None = None) -> dict:
        if not self.api_key:
            raise RuntimeError("TMDB_API_KEY missing.")

        url = f"{self.base_url}{endpoint}"
        default_params = {"api_key": self.api_key, "language": self.language}
        if params:
            default_params.update(params)

        attempts = 0
        last_exc: Exception | None = None

        while attempts < 3:
            try:
                client = await self._get_client()
                response = await client.get(url, params=default_params)

                if response.status_code == 404:
                    return {}

                response.raise_for_status()

                if not response.text:
                    return {}

                try:
                    return response.json()
                except ValueError as e:
                    logger.error(f"TMDB JSON Error: {e}")
                    return {}

            except httpx.HTTPStatusError as e:
                status = e.response.status_code
                if status == 429 or 500 <= status < 600:
                    attempts += 1
                    await asyncio.sleep((2 ** (attempts - 1)) + random.uniform(0, 0.25))
                    last_exc = e
                    continue
                logger.error(f"TMDB {status}: {e.response.text[:200]}")
                raise
            except httpx.RequestError as e:
                attempts += 1
                await asyncio.sleep((2 ** (attempts - 1)) + random.uniform(0, 0.25))
                last_exc = e
                continue

        if last_exc:
            raise last_exc
        return {}


class TMDBService(TMDBClient):
    """Facade for TMDB API endpoints.

    Uses strictly In-Memory Caching (L1) to avoid Redis usage.
    """

    @alru_cache(maxsize=1000)
    async def find_by_imdb_id(self, imdb_id: str) -> tuple[int | None, str | None]:
        data = await self.make_request(f"/find/{imdb_id}", {"external_source": "imdb_id"})
        if not data:
            return None, None

        if data.get("movie_results"):
            return data["movie_results"][0].get("id"), "movie"
        if data.get("tv_results"):
            return data["tv_results"][0].get("id"), "tv"
        return None, None

    @alru_cache(maxsize=1000)
    async def get_movie_details(self, movie_id: int) -> dict:
        return await self.make_request(f"/movie/{movie_id}", {"append_to_response": "credits,external_ids,keywords"})

    @alru_cache(maxsize=1000)
    async def get_tv_details(self, tv_id: int) -> dict:
        return await self.make_request(f"/tv/{tv_id}", {"append_to_response": "credits,external_ids,keywords"})

    @alru_cache(maxsize=100)
    async def get_recommendations(self, tmdb_id: int, media_type: str, page: int = 1) -> dict:
        return await self.make_request(f"/{media_type}/{tmdb_id}/recommendations", {"page": page})

    @alru_cache(maxsize=100)
    async def get_similar(self, tmdb_id: int, media_type: str, page: int = 1) -> dict:
        return await self.make_request(f"/{media_type}/{tmdb_id}/similar", {"page": page})

    @alru_cache(maxsize=50)
    async def get_trending(self, media_type: str, time_window: str = "week", page: int = 1) -> dict:
        return await self.make_request(f"/trending/{media_type}/{time_window}", {"page": page})

    @alru_cache(maxsize=50)
    async def get_top_rated(self, media_type: str, page: int = 1) -> dict:
        return await self.make_request(f"/{media_type}/top_rated", {"page": page})

    @alru_cache(maxsize=100)
    async def get_discover(self, media_type: str, page: int = 1, **kwargs) -> dict:
        media_type = "movie" if media_type == "movie" else "tv"
        params = {"page": str(page)}
        params.update({k: str(v) for k, v in kwargs.items()})
        # Sort params to ensure cache key consistency
        params = dict(sorted(params.items()))
        return await self.make_request(f"/discover/{media_type}", params)


# Singleton Facade
@functools.lru_cache(maxsize=16)
def get_tmdb_service(language: str = "en-US") -> TMDBService:
    return TMDBService(language=language)
