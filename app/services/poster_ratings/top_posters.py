from typing import Literal
from urllib.parse import urlencode

import httpx

from app.core.version import __version__


class TopPostersService:
    def __init__(self):
        self.base_url = "https://api.top-streaming.stream"
        self.headers = {
            "User-Agent": f"Watchly/{__version__} (+https://github.com/TimilsinaBimal/Watchly)",
            "Accept": "application/json",
        }
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=10.0, headers=self.headers)
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def validate_api_key(self, api_key: str) -> bool:
        url = f"{self.base_url}/auth/verify/{api_key}"
        response = await self._get_client().get(url)
        response.raise_for_status()
        json_data = response.json()
        return json_data.get("valid", False)

    def get_poster_url(self, api_key: str, provider: Literal["imdb", "tmdb", "tvdb"], item_id: str, **kwargs) -> str:
        url = f"{self.base_url}/{api_key}/{provider}/poster-default/{item_id}.jpg"

        poster_url = f"{url}?{urlencode(kwargs)}"
        return poster_url
