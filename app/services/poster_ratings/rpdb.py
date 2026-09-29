from typing import Literal
from urllib.parse import urlencode

from app.core.base_client import BaseClient


class RPDBService(BaseClient):
    def __init__(self):
        super().__init__(base_url="https://api.ratingposterdb.com", timeout=10.0)

    async def validate_api_key(self, api_key: str) -> bool:
        # Straight to the client, not self.get: the key is in the path, and
        # BaseClient logs the path of every failed request.
        response = await (await self.get_client()).get(f"/{api_key}/isValid")
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
