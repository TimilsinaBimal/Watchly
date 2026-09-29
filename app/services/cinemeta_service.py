from typing import Any

import httpx

from app.core.base_client import BaseClient


class CinemetaService(BaseClient):
    def __init__(self):
        super().__init__(base_url="https://v3-cinemeta.strem.io", timeout=10.0)

    async def get_metadata(self, imdb_id: str, content_type: str) -> dict[str, Any]:
        try:
            data = await self.get(f"/meta/{content_type}/{imdb_id}.json")
        except httpx.HTTPError:
            # BaseClient has already logged the failed request.
            return {}
        return data.get("meta", {})


cinemeta_service = CinemetaService()
