from app.core.base_client import BaseClient


class StremioClient(BaseClient):
    """
    Client for interacting with the main Stremio API.
    """

    def __init__(self, timeout: float = 10.0, max_retries: int = 3):
        headers = {
            "User-Agent": "Watchly/Client",
            "Accept": "application/json",
        }
        super().__init__(base_url="https://api.strem.io", timeout=timeout, max_retries=max_retries, headers=headers)


class StremioLikesClient(BaseClient):
    """
    Client for interacting with the Stremio Likes API.
    """

    def __init__(self, timeout: float = 10.0, max_retries: int = 3):
        headers = {
            "User-Agent": "Watchly/Client",
            "Accept": "application/json",
        }
        super().__init__(
            base_url="https://likes.stremio.com", timeout=timeout, max_retries=max_retries, headers=headers
        )
