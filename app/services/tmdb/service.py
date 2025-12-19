from typing import Any

from async_lru import alru_cache
from loguru import logger

from app.services.tmdb.client import TMDBClient


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

    @alru_cache(maxsize=2000)
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
            logger.warning(f"Error finding TMDB ID for IMDB {imdb_id}: {e}")
            return None, None

    @alru_cache(maxsize=5000)
    async def get_movie_details(self, movie_id: int) -> dict[str, Any]:
        """Get details of a specific movie with credits and keywords."""
        params = {"append_to_response": "credits,external_ids,keywords"}
        return await self.client.get(f"/movie/{movie_id}", params=params)

    @alru_cache(maxsize=5000)
    async def get_tv_details(self, tv_id: int) -> dict[str, Any]:
        """Get details of a specific TV series with credits and keywords."""
        params = {"append_to_response": "credits,external_ids,keywords"}
        return await self.client.get(f"/tv/{tv_id}", params=params)

    @alru_cache(maxsize=1000, ttl=21600)  # 6 hours
    async def get_recommendations(self, tmdb_id: int, media_type: str, page: int = 1) -> dict[str, Any]:
        """Get recommendations based on TMDB ID and media type."""
        params = {"page": page}
        return await self.client.get(f"/{media_type}/{tmdb_id}/recommendations", params=params)

    @alru_cache(maxsize=1000, ttl=21600)
    async def get_similar(self, tmdb_id: int, media_type: str, page: int = 1) -> dict[str, Any]:
        """Get similar content based on TMDB ID and media type."""
        params = {"page": page}
        return await self.client.get(f"/{media_type}/{tmdb_id}/similar", params=params)

    @alru_cache(maxsize=1000, ttl=1800)  # 30 mins
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
        params.update(kwargs)
        return await self.client.get(f"/discover/{mt}", params=params)

    @alru_cache(maxsize=1000)
    async def get_keyword_details(self, keyword_id: int) -> dict[str, Any]:
        """Get details of a specific keyword."""
        return await self.client.get(f"/keyword/{keyword_id}")

    @alru_cache(maxsize=500, ttl=3600)  # 1 hour
    async def get_trending(self, media_type: str, time_window: str = "week", page: int = 1) -> dict[str, Any]:
        """Get trending content."""
        mt = "movie" if media_type == "movie" else "tv"
        params = {"page": page}
        return await self.client.get(f"/trending/{mt}/{time_window}", params=params)

    @alru_cache(maxsize=500, ttl=3600)
    async def get_top_rated(self, media_type: str, page: int = 1) -> dict[str, Any]:
        """Get top-rated content list."""
        mt = "movie" if media_type == "movie" else "tv"
        params = {"page": page}
        return await self.client.get(f"/{mt}/top_rated", params=params)
