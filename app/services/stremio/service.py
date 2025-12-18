from app.services.stremio.addons import StremioAddonService
from app.services.stremio.auth import StremioAuthService
from app.services.stremio.client import StremioClient, StremioLikesClient
from app.services.stremio.library import StremioLibraryService


class StremioBundle:
    """
    A unified bundle for all Stremio-related services.
    Provides a clean interface for the rest of the application.
    """

    def __init__(self):
        self._client = StremioClient()
        self._likes_client = StremioLikesClient()

        self.auth = StremioAuthService(self._client)
        self.library = StremioLibraryService(self._client, self._likes_client)
        self.addons = StremioAddonService(self._client)

    async def close(self):
        """Close all underlying HTTP clients."""
        await self._client.close()
        await self._likes_client.close()
