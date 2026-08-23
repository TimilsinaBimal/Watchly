from typing import Literal
from urllib.parse import urlencode

import httpx

from app.core.version import __version__


class TopPostersService:
    def __init__(self):
        # Moved from api.top-streaming.stream, which 301s here for both the verify
        # and the poster paths. httpx does not follow redirects by default, so every
        # key validation was failing on the redirect rather than on the key (#158).
        self.base_url = "https://api.top-posters.com"
        self.headers = {
            "User-Agent": f"Watchly/{__version__} (+https://github.com/TimilsinaBimal/Watchly)",
            "Accept": "application/json",
        }
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            # Redirects followed so the next time they move a domain this degrades to
            # an extra hop instead of every key looking invalid.
            self._client = httpx.AsyncClient(timeout=10.0, headers=self.headers, follow_redirects=True)
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def validate_api_key(self, api_key: str) -> bool:
        """Whether the provider recognises this key.

        The status is the real signal: an unknown key answers 404 with
        {"detail": "API Key not found"}. The body's `valid` flag is honoured when
        present rather than assumed, so a response shape change can't turn every
        working key into a rejected one.
        """
        response = await self._get_client().get(f"{self.base_url}/auth/verify/{api_key}")
        if response.status_code == 404:
            return False

        response.raise_for_status()
        try:
            return bool(response.json().get("valid", True))
        except ValueError:
            return True

    def get_poster_url(self, api_key: str, provider: Literal["imdb", "tmdb", "tvdb"], item_id: str, **kwargs) -> str:
        url = f"{self.base_url}/{api_key}/{provider}/poster-default/{item_id}.jpg"

        poster_url = f"{url}?{urlencode(kwargs)}"
        return poster_url
