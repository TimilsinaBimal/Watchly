import functools
from typing import Any

from app.core.config import settings
from app.services.tmdb.service import TMDBService as ModularTMDBService


class TMDBService:
    """
    Proxy class for backward compatibility.
    Delegates all calls to the modular TMDBService.
    """

    def __init__(self, language: str = "en-US"):
        self._service = ModularTMDBService(api_key=settings.TMDB_API_KEY, language=language)

    async def close(self):
        await self._service.close()

    async def find_by_imdb_id(self, imdb_id: str) -> tuple[int | None, str | None]:
        return await self._service.find_by_imdb_id(imdb_id)

    async def get_movie_details(self, movie_id: int) -> dict[str, Any]:
        return await self._service.get_movie_details(movie_id)

    async def get_tv_details(self, tv_id: int) -> dict[str, Any]:
        return await self._service.get_tv_details(tv_id)

    async def get_recommendations(self, tmdb_id: int, media_type: str, page: int = 1) -> dict[str, Any]:
        return await self._service.get_recommendations(tmdb_id, media_type, page)

    async def get_similar(self, tmdb_id: int, media_type: str, page: int = 1) -> dict[str, Any]:
        return await self._service.get_similar(tmdb_id, media_type, page)

    async def get_discover(self, media_type: str, **kwargs) -> dict[str, Any]:
        return await self._service.get_discover(media_type, **kwargs)

    async def get_trending(self, media_type: str, time_window: str = "week", page: int = 1) -> dict[str, Any]:
        return await self._service.get_trending(media_type, time_window, page)

    async def get_top_rated(self, media_type: str, page: int = 1) -> dict[str, Any]:
        return await self._service.get_top_rated(media_type, page)


@functools.lru_cache(maxsize=16)
def get_tmdb_service(language: str = "en-US") -> TMDBService:
    return TMDBService(language=language)
