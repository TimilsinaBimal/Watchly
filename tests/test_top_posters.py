import asyncio

import httpx
import pytest

from app.services.poster_ratings.top_posters import TopPostersService


class FakeClient:
    def __init__(self, status: int, body=None):
        self.status = status
        self.body = body
        self.requested: list[str] = []

    async def get(self, url):
        self.requested.append(url)
        return httpx.Response(self.status, json=self.body, request=httpx.Request("GET", url))


def service(status: int, body=None) -> tuple[TopPostersService, FakeClient]:
    svc = TopPostersService()
    client = FakeClient(status, body)
    svc._get_client = lambda: client
    return svc, client


def validate(svc, key="k") -> bool:
    return asyncio.run(svc.validate_api_key(key))


def test_unknown_key_is_rejected_without_raising():
    """The provider answers 404 for a key it doesn't know, which is an answer rather
    than a failure — raising made it surface as 'could not validate'."""
    svc, _ = service(404, {"detail": "API Key not found"})

    assert validate(svc) is False


def test_known_key_is_accepted():
    svc, client = service(200, {"valid": True})

    assert validate(svc) is True
    assert client.requested == ["https://api.top-posters.com/auth/verify/k"]


def test_a_200_without_the_valid_flag_still_counts_as_valid():
    """Status is the contract we observed; don't reject a working key just because
    the body shape moved."""
    svc, _ = service(200, {"key": "k", "tier": "pro"})

    assert validate(svc) is True


def test_an_explicit_false_flag_is_respected():
    svc, _ = service(200, {"valid": False})

    assert validate(svc) is False


def test_server_errors_still_raise():
    """A 500 is not an answer about the key, so it must not read as 'invalid'."""
    svc, _ = service(500, {"detail": "boom"})

    with pytest.raises(httpx.HTTPStatusError):
        validate(svc)


def test_requests_use_the_current_domain():
    svc = TopPostersService()

    assert svc.base_url == "https://api.top-posters.com"
    assert "top-streaming" not in svc.get_poster_url("k", "imdb", "tt0468569")


def test_client_follows_redirects():
    """The old domain 301s to the new one; not following it is what broke #158."""
    svc = TopPostersService()
    try:
        assert svc._get_client().follow_redirects is True
    finally:
        asyncio.run(svc.close())
