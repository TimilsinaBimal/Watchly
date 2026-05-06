from app.services.trakt.auth import TraktAuthService
from app.services.trakt.client import TraktClient
from app.services.trakt.library import TraktLibraryService
from app.services.trakt.user import TraktUserService


class TraktBundle:
    """
    Unified bundle for all Trakt-related services.
    """

    def __init__(self, client_id: str, client_secret: str, redirect_uri: str, access_token: str | None = None):
        self.auth = TraktAuthService(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
        )
        self._client = TraktClient(client_id=client_id, access_token=access_token)
        self.user = TraktUserService(self._client)
        self.library = TraktLibraryService(self._client)

    async def close(self):
        await self._client.close()
