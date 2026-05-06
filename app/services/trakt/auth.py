import secrets
from typing import Any

import httpx


# Module-level shared client for connection pooling across token exchanges.
# auth.py only talks to one endpoint (api.trakt.tv/oauth/token) so a single
# persistent client is sufficient and avoids the overhead of creating a new
# TCP connection for every OAuth exchange.
_http_client: httpx.AsyncClient | None = None


def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(timeout=15.0)
    return _http_client


class TraktAuthService:
    """
    Handles Trakt OAuth2 authentication (Authorization Code flow).
    """

    TOKEN_URL = "https://api.trakt.tv/oauth/token"
    AUTHORIZE_URL = "https://trakt.tv/oauth/authorize"

    def __init__(self, client_id: str, client_secret: str, redirect_uri: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri

    def get_authorize_url(self, state: str | None = None) -> tuple[str, str]:
        """
        Build the OAuth2 authorization URL and return it along with the state value.
        """
        if not state:
            state = secrets.token_urlsafe(16)

        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "state": state,
        }
        query = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{self.AUTHORIZE_URL}?{query}", state

    async def exchange_code(self, code: str) -> dict[str, Any]:
        """
        Exchange an authorization code for tokens.
        Returns dict with access_token, refresh_token, expires_in, etc.
        """
        payload = {
            "code": code,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": self.redirect_uri,
            "grant_type": "authorization_code",
        }
        client = _get_http_client()
        response = await client.post(self.TOKEN_URL, json=payload)
        response.raise_for_status()
        return response.json()

    async def refresh_token(self, refresh_token_value: str) -> dict[str, Any]:
        """Refresh an expired access token."""
        payload = {
            "refresh_token": refresh_token_value,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": self.redirect_uri,
            "grant_type": "refresh_token",
        }
        client = _get_http_client()
        response = await client.post(self.TOKEN_URL, json=payload)
        response.raise_for_status()
        return response.json()
