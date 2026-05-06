from typing import Any

from loguru import logger

from app.services.trakt.client import TraktClient


class TraktUserService:
    """
    Fetches the authenticated Trakt user's profile.
    """

    def __init__(self, client: TraktClient):
        self.client = client

    async def get_user_info(self) -> dict[str, Any]:
        """Return the authenticated user's profile (username, name, etc.)."""
        try:
            data = await self.client.get("/users/me?extended=full")
            return data
        except Exception as e:
            logger.exception(f"Failed to fetch Trakt user info: {e}")
            raise
