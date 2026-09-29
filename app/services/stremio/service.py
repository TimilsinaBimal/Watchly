from app.core.base_client import BaseClient
from app.services.stremio.addons import StremioAddonService
from app.services.stremio.auth import StremioAuthService
from app.services.stremio.library import StremioLibraryService

_HEADERS = {"User-Agent": "Watchly/Client", "Accept": "application/json"}


class StremioBundle:
    def __init__(self):
        self._client = BaseClient(base_url="https://api.strem.io", headers=_HEADERS)
        self._likes_client = BaseClient(base_url="https://likes.stremio.com", headers=_HEADERS)

        self.auth = StremioAuthService(self._client)
        self.library = StremioLibraryService(self._client, self._likes_client)
        self.addons = StremioAddonService(self._client)

    async def close(self):
        await self._client.close()
        await self._likes_client.close()
