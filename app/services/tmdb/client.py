from typing import Any

from app.core.base_client import BaseClient
from app.core.version import __version__


class TMDBClient(BaseClient):
    """
    Client for interacting with the TMDB API.
    """

    def __init__(self, api_key: str, language: str = "en-US", timeout: float = 10.0, max_retries: int = 3):
        headers = {
            "User-Agent": f"Watchly/{__version__} (+https://github.com/TimilsinaBimal/Watchly)",
            "Accept": "application/json",
        }
        super().__init__(
            base_url="https://api.themoviedb.org/3", timeout=timeout, max_retries=max_retries, headers=headers
        )
        self.api_key = api_key
        self.language = language

    async def _request(self, method: str, url: str, **kwargs) -> Any:
        """Override request to always include API key and language."""
        params = kwargs.get("params", {})
        if params is None:
            params = {}
        params["api_key"] = self.api_key
        params["language"] = self.language
        kwargs["params"] = params
        return await super()._request(method, url, **kwargs)
