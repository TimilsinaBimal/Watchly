import asyncio
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import httpx
import pytest
from loguru import logger

from app.core.base_client import BaseClient


def test_parse_retry_after_delta_seconds():
    assert BaseClient._parse_retry_after("5") == 5.0
    assert BaseClient._parse_retry_after("0") == 0.0
    assert BaseClient._parse_retry_after("  12  ") == 12.0


def test_parse_retry_after_absent_or_garbage():
    assert BaseClient._parse_retry_after(None) is None
    assert BaseClient._parse_retry_after("") is None
    assert BaseClient._parse_retry_after("soon") is None


def test_parse_retry_after_http_date_future():
    future = datetime.now(timezone.utc) + timedelta(seconds=30)
    val = BaseClient._parse_retry_after(format_datetime(future))
    assert val is not None
    assert 20.0 <= val <= 31.0


def test_parse_retry_after_http_date_in_past_is_clamped_to_zero():
    assert BaseClient._parse_retry_after("Wed, 21 Oct 2015 07:28:00 GMT") == 0.0


def test_a_failed_request_never_logs_the_query_string():
    """TMDB and Simkl carry the user's key in the query string, and str() of an
    httpx error includes the full URL."""

    def reject(request):
        return httpx.Response(401, request=request)

    client = BaseClient(base_url="https://api.example.test", max_retries=1)
    client._client = httpx.AsyncClient(base_url=client.base_url, transport=httpx.MockTransport(reject))
    lines: list[str] = []
    sink = logger.add(lines.append, format="{message}")
    try:
        with pytest.raises(httpx.HTTPStatusError):
            asyncio.run(client.get("/movie/1", params={"api_key": "SECRET"}))
    finally:
        logger.remove(sink)

    assert lines and not any("SECRET" in line for line in lines)


def test_log_url_replaces_a_path_that_carries_a_secret():
    def reject(request):
        return httpx.Response(401, request=request)

    client = BaseClient(base_url="https://likes.example.test", max_retries=1)
    client._client = httpx.AsyncClient(base_url=client.base_url, transport=httpx.MockTransport(reject))
    lines: list[str] = []
    sink = logger.add(lines.append, format="{message}")
    try:
        with pytest.raises(httpx.HTTPStatusError):
            asyncio.run(client.get("/addons/SECRET/catalog.json", log_url="/addons/{token}/catalog.json"))
    finally:
        logger.remove(sink)

    assert lines and not any("SECRET" in line for line in lines)
