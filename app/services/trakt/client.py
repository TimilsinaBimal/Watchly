from app.core.base_client import BaseClient


class TraktClient(BaseClient):
    """
    Client for interacting with the Trakt API.
    """

    def __init__(self, client_id: str, access_token: str | None = None, timeout: float = 10.0, max_retries: int = 3):
        headers = {
            "Content-Type": "application/json",
            "trakt-api-version": "2",
            "trakt-api-key": client_id,
        }
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"

        super().__init__(base_url="https://api.trakt.tv", timeout=timeout, max_retries=max_retries, headers=headers)
