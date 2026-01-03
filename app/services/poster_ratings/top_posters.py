from typing import Literal
from urllib.parse import urlencode

import httpx


class TopPostersService:
    def __init__(self):
        self.base_url = "https://api.top-streaming.stream"

    async def validate_api_key(self, api_key: str) -> bool:
        url = f"{self.base_url}/auth/verify/{api_key}"
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            json_data = response.json()
            return json_data.get("valid", False)

    def get_poster_url(self, api_key: str, provider: Literal["imdb", "tmdb", "tvdb"], item_id: str, **kwargs) -> str:
        url = f"{self.base_url}/{api_key}/{provider}/poster-default/{item_id}.jpg"

        poster_url = f"{url}?{urlencode(kwargs)}"
        return poster_url
