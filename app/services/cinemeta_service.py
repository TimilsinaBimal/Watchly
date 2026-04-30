import json

import httpx
from loguru import logger


class CinemetaService:
    def __init__(self):
        self.base_url = "https://v3-cinemeta.strem.io"
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=10.0, follow_redirects=True)
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def get_metadata(self, imdb_id: str, content_type: str) -> dict[str, any]:
        url = f"{self.base_url}/meta/{content_type}/{imdb_id}.json"
        client = self._get_client()
        try:
            response = await client.get(url)
            response.raise_for_status()
            json_response = response.json()
            return json_response.get("meta", {})
        except (httpx.HTTPStatusError, httpx.RequestError, json.JSONDecodeError) as e:
            logger.error(f"Error getting metadata for {imdb_id}: {e}")
            return {}


cinemeta_service = CinemetaService()
