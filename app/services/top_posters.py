from httpx import AsyncClient, HTTPStatusError
from loguru import logger


class TopPosters:
    def __init__(self):
        self.client = AsyncClient(timeout=5)
        self.base_url = "https://api.top-streaming.stream"

    async def validate(self, api_key: str) -> bool:
        url = f"{self.base_url}/auth/verify/{api_key}"
        try:
            req = await self.client.get(url)
            req.raise_for_status()
            return True
        except HTTPStatusError as e:
            logger.warning(f"Invalid API Key: {e}")
        except Exception as e:
            logger.error(f"Unexpected error while validations rpdb key: {e}")
        return False

    def get_poster(self, api_key: str, item_id: str, language: str) -> str:
        url = f"{self.base_url}/{api_key}/imdb/poster-default/{item_id}.jpg?lang={language}"
        return url
