import asyncio
from typing import Any

import httpx
from loguru import logger


class BaseClient:
    """
    Base asynchronous HTTP client with built-in retry logic and logging.
    """

    def __init__(
        self, base_url: str = "", timeout: float = 10.0, max_retries: int = 3, headers: dict[str, str] | None = None
    ):
        self.base_url = base_url
        self.timeout = timeout
        self.max_retries = max_retries
        self.headers = headers or {}
        self._client: httpx.AsyncClient | None = None

    async def get_client(self) -> httpx.AsyncClient:
        """Get or create the httpx.AsyncClient instance."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url, timeout=self.timeout, headers=self.headers, follow_redirects=True
            )
        return self._client

    async def close(self):
        """Close the underlying HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def _request(self, method: str, url: str, max_tries: int | None = None, **kwargs) -> httpx.Response:
        """Internal request handler with retry logic."""
        client = await self.get_client()
        tries = max_tries or self.max_retries
        last_exception = None

        for attempt in range(1, tries + 1):
            try:
                response = await client.request(method, url, **kwargs)
                response.raise_for_status()
                return response
            except (httpx.HTTPStatusError, httpx.RequestError) as e:
                last_exception = e
                if attempt < tries:
                    wait_time = 0.5 * (2 ** (attempt - 1))  # Exponential backoff
                    logger.warning(
                        f"Request failed ({method} {url}): {str(e)}. "
                        f"Retrying in {wait_time}s... (Attempt {attempt}/{tries})"
                    )
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"Request failed after {tries} attempts: {str(e)}")

        if last_exception:
            raise last_exception
        raise httpx.RequestError("Request failed for unknown reasons")

    async def get(self, url: str, params: dict[str, Any] | None = None, **kwargs) -> dict[str, Any]:
        """Perform a GET request and return the JSON response."""
        response = await self._request("GET", url, params=params, **kwargs)
        return response.json()

    async def post(self, url: str, json: dict[str, Any] | None = None, **kwargs) -> dict[str, Any]:
        """Perform a POST request and return the JSON response."""
        response = await self._request("POST", url, json=json, **kwargs)
        return response.json()
