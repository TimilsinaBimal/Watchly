from typing import Literal
from urllib.parse import urlencode

from app.core.base_client import BaseClient
from app.core.version import __version__


class TopPostersService(BaseClient):
    def __init__(self):
        # Moved from api.top-streaming.stream, which 301s here for both the verify
        # and the poster paths (#158). BaseClient follows redirects, so the next
        # domain move costs an extra hop instead of every key looking invalid.
        super().__init__(
            base_url="https://api.top-posters.com",
            timeout=10.0,
            headers={
                "User-Agent": f"Watchly/{__version__} (+https://github.com/TimilsinaBimal/Watchly)",
                "Accept": "application/json",
            },
        )

    async def validate_api_key(self, api_key: str) -> bool:
        """Whether the provider recognises this key.

        The status is the real signal: an unknown key answers 404 with
        {"detail": "API Key not found"}. The body's `valid` flag is honoured when
        present rather than assumed, so a response shape change can't turn every
        working key into a rejected one.
        """
        # Straight to the client, not self.get: the key is in the path, and
        # BaseClient logs the path of every failed request.
        response = await (await self.get_client()).get(f"/auth/verify/{api_key}")
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
