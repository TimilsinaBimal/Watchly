import secrets
from typing import Any

import httpx


class TraktAuthService:
    """
    Handles Trakt OAuth2 authentication (Device Code / Authorization Code flows).
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
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(self.TOKEN_URL, json=payload)
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.exception(f"Trakt token exchange failed: {e}")
            raise

    async def refresh_token(self, refresh_token_value: str) -> dict[str, Any]:
        """Refresh an expired access token."""
        payload = {
            "refresh_token": refresh_token_value,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": self.redirect_uri,
            "grant_type": "refresh_token",
        }
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(self.TOKEN_URL, json=payload)
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.exception(f"Trakt token refresh failed: {e}")
            raise
