import asyncio

import httpx
from loguru import logger


class StremioClient:
    """Base client configuration for Stremio Services."""

    def __init__(self):
        self.base_url = "https://api.strem.io"
        self._client: httpx.AsyncClient | None = None
        self._likes_client: httpx.AsyncClient | None = None

    async def get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=10.0,
                limits=httpx.Limits(max_keepalive_connections=10, max_connections=50),
                http2=True,
                headers={
                    "User-Agent": "Watchly/Client",
                    "Accept": "application/json",
                },
            )
        return self._client

    async def get_likes_client(self) -> httpx.AsyncClient:
        if self._likes_client is None:
            self._likes_client = httpx.AsyncClient(
                timeout=10.0,
                limits=httpx.Limits(max_keepalive_connections=10, max_connections=50),
                http2=True,
                headers={
                    "User-Agent": "Watchly/Client",
                    "Accept": "application/json",
                },
            )
        return self._likes_client

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
        if self._likes_client:
            await self._likes_client.aclose()
            self._likes_client = None

    async def post_with_retries(self, url: str, json: dict, max_tries: int = 3) -> dict:
        client = await self.get_client()
        attempts = 0
        while attempts < max_tries:
            try:
                resp = await client.post(url, json=json)
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPError:
                attempts += 1
                await asyncio.sleep(0.5 * attempts)
                if attempts == max_tries:
                    raise
        return {}

    async def get_with_retries(self, url: str, params: dict | None = None, max_tries: int = 3) -> dict:
        client = await self.get_client()  # Actually uses likes client for GET usually, handle in caller or separate
        # Fixing logic: likes are on separate domain. Here we assume generic usage.
        # But for specific Stremio/Likes domain, caller should provide correct client or URL.
        # We will use get_client() as default, but likes need specialized.
        try:
            if "likes.stremio" in url:
                client = await self.get_likes_client()

            resp = await client.get(url, params=params)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.warning(f"GET {url} failed: {e}")
            return {}
