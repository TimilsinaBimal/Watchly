from typing import Literal
from urllib.parse import urlencode

import httpx


class RPDBService:
    def __init__(self):
        self.base_url = "https://api.ratingposterdb.com"
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=10.0)
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def validate_api_key(self, api_key: str) -> bool:
        url = f"{self.base_url}/{api_key}/isValid"
        response = await self._get_client().get(url)
        return response.status_code == 200

    def get_poster_url(
        self,
        api_key: str,
        provider: Literal["imdb", "tmdb", "tvdb"],
        item_id: str,
        fallback: str,
    ) -> str:
        url = f"{self.base_url}/{api_key}/{provider}/poster-default/{item_id}.jpg"
        params = {"fallback": "true"}

        poster_url = f"{url}?{urlencode(params)}"
        return poster_url
