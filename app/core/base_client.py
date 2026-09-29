import asyncio
import random
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import httpx
from loguru import logger

# Cap how long we'll honor a 429 Retry-After, so a hostile or buggy upstream
# can't stall an in-flight request (holding a connection) indefinitely.
_RETRY_AFTER_CEILING_SECONDS = 8.0


class BaseClient:
    def __init__(
        self, base_url: str = "", timeout: float = 10.0, max_retries: int = 3, headers: dict[str, str] | None = None
    ):
        self.base_url = base_url
        self.timeout = timeout
        self.max_retries = max_retries
        self.headers = headers or {}
        self._client: httpx.AsyncClient | None = None

    async def get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url, timeout=self.timeout, headers=self.headers, follow_redirects=True
            )
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        client = await self.get_client()
        tries = self.max_retries

        for attempt in range(1, tries + 1):
            try:
                response = await client.request(method, url, **kwargs)
                response.raise_for_status()
                return response
            except (httpx.HTTPStatusError, httpx.RequestError) as e:

                # Check if the error is retryable
                is_retryable = True
                if isinstance(e, httpx.HTTPStatusError):
                    # Only retry on 429 (Rate Limit) and 5xx (Server Errors)
                    # 404, 400, 401, etc. are not retryable
                    is_retryable = e.response.status_code in (429, 500, 502, 503, 504)

                if is_retryable and attempt < tries:
                    # Exponential backoff + small random jitter to avoid retry
                    # stampedes when many concurrent users hit the same 429.
                    wait_time = 0.5 * (2 ** (attempt - 1)) + random.uniform(0, 0.25)
                    # On a 429, wait out the server-specified window instead of
                    # burning all retries inside it (which otherwise drops the
                    # request after ~1.5s when the limit window is longer).
                    if isinstance(e, httpx.HTTPStatusError) and e.response.status_code == 429:
                        retry_after = self._parse_retry_after(e.response.headers.get("retry-after"))
                        if retry_after is not None:
                            wait_time = min(max(retry_after, wait_time), _RETRY_AFTER_CEILING_SECONDS)
                    logger.warning(
                        f"Request failed ({method} {url}): {self._describe(e)}. "
                        f"Retrying in {wait_time:.2f}s (attempt {attempt}/{tries})"
                    )
                    await asyncio.sleep(wait_time)
                else:
                    if not is_retryable:
                        logger.error(f"Non-retryable request failure ({method} {url}): {self._describe(e)}")
                    else:
                        logger.error(f"Request failed after {tries} attempts ({method} {url}): {self._describe(e)}")
                    raise

        raise httpx.RequestError(f"Request failed for {method} {url} with 0 attempts configured")

    @staticmethod
    def _describe(e: httpx.HTTPError) -> str:
        # str() of an httpx error carries the full URL, and TMDB and Simkl put the
        # user's key in the query string.
        if isinstance(e, httpx.HTTPStatusError):
            return f"HTTP {e.response.status_code}"
        return type(e).__name__

    @staticmethod
    def _parse_retry_after(value: str | None) -> float | None:
        """Parse a Retry-After header (delta-seconds or HTTP-date) into seconds.

        Returns None when the header is absent or unparseable so the caller
        falls back to the computed exponential backoff.
        """
        if not value:
            return None
        value = value.strip()
        try:
            return max(float(value), 0.0)
        except ValueError:
            pass
        try:
            retry_dt = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
        if retry_dt is None:
            return None
        if retry_dt.tzinfo is None:
            retry_dt = retry_dt.replace(tzinfo=timezone.utc)
        return max((retry_dt - datetime.now(timezone.utc)).total_seconds(), 0.0)

    @staticmethod
    def _safe_json(response: httpx.Response, method: str, url: str) -> dict[str, Any]:
        """Parse JSON body, returning {} on empty/non-JSON 2xx responses."""
        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError as e:
            logger.warning(f"Non-JSON body from {method} {url} (status={response.status_code}): {e}")
            return {}

    async def get(self, url: str, params: dict[str, Any] | None = None, **kwargs) -> dict[str, Any]:
        response = await self._request("GET", url, params=params, **kwargs)
        return self._safe_json(response, "GET", url)

    async def post(self, url: str, json: dict[str, Any] | None = None, **kwargs) -> dict[str, Any]:
        response = await self._request("POST", url, json=json, **kwargs)
        return self._safe_json(response, "POST", url)
