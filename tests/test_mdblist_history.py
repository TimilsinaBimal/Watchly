import asyncio

import httpx
import pytest

from app.services.mdblist import MDBListService

GOOD_KEY = "good-key"

WATCHED_PAGE_1 = {
    "movies": [
        {"watched_at": "2026-01-05T22:27:00Z", "movie": {"title": "Heat", "ids": {"imdb": "tt0113277", "tmdb": 949}}},
        {"watched_at": None, "movie": {"title": "No imdb id", "ids": {"tmdb": 1}}},
    ],
    "shows": [],
    "pagination": {"next_cursor": "page-2"},
}
WATCHED_PAGE_2 = {
    "movies": [],
    "shows": [{"watched_at": "2025-10-15T20:00:00Z", "show": {"title": "The Wire", "ids": {"imdb": "tt0306414"}}}],
    "pagination": {"next_cursor": None},
}
RATINGS = {
    "movies": [
        {"rated_at": "2026-01-06T00:00:00Z", "rating": 9, "movie": {"title": "Heat", "ids": {"imdb": "tt0113277"}}},
    ],
    "shows": [
        {"rated_at": "2025-12-01T00:00:00Z", "rating": 7, "show": {"title": "Rated", "ids": {"imdb": "tt0000001"}}},
    ],
    "pagination": {},
}


class FakeClient:
    """Answers only the good key; anything else is a 401 like the real API."""

    def __init__(self, status_for_good_key: int | None = None):
        self.status_for_good_key = status_for_good_key
        self.calls: list[tuple[str, dict]] = []

    async def get(self, url: str, params=None, **kwargs):
        self.calls.append((url, dict(params)))
        if params.get("apikey") != GOOD_KEY:
            self._raise(url, 401)
        if self.status_for_good_key:
            self._raise(url, self.status_for_good_key)
        if url == "/sync/ratings":
            return RATINGS
        return WATCHED_PAGE_2 if params.get("cursor") == "page-2" else WATCHED_PAGE_1

    @staticmethod
    def _raise(url: str, status: int):
        request = httpx.Request("GET", f"https://api.mdblist.com{url}")
        raise httpx.HTTPStatusError("rejected", request=request, response=httpx.Response(status, request=request))


def service_with(client: FakeClient) -> MDBListService:
    service = MDBListService()
    service.client = client
    return service


def test_history_merges_pages_and_ratings():
    client = FakeClient()
    history = asyncio.run(service_with(client).get_history(GOOD_KEY))

    by_id = {item.imdb_id: item for item in history.items}
    assert history.source == "mdblist"
    assert set(by_id) == {"tt0113277", "tt0306414", "tt0000001"}

    heat = by_id["tt0113277"]
    assert heat.type == "movie" and heat.rating == 9.0 and heat.watch_count == 1 and heat.completion == 1.0
    assert heat.last_watched is not None and heat.last_watched.year == 2026

    wire = by_id["tt0306414"]
    assert wire.type == "series" and wire.rating is None

    rated_only = by_id["tt0000001"]
    assert rated_only.type == "series" and rated_only.rating == 7.0
    assert rated_only.watch_count == 0 and rated_only.completion == 0.0

    watched_calls = [params for url, params in client.calls if url == "/sync/watched"]
    assert [params.get("cursor") for params in watched_calls] == [None, "page-2"]


def test_a_rejected_key_raises_instead_of_an_empty_history():
    with pytest.raises(httpx.HTTPStatusError) as exc:
        asyncio.run(service_with(FakeClient()).get_history("stale-key"))
    assert exc.value.response.status_code == 401


def test_an_outage_raises_instead_of_an_empty_history():
    with pytest.raises(httpx.HTTPStatusError) as exc:
        asyncio.run(service_with(FakeClient(status_for_good_key=503)).get_history(GOOD_KEY))
    assert exc.value.response.status_code == 503


def settings_with_mdblist_key(api_key: str):
    from app.core.settings import get_default_settings

    user_settings = get_default_settings()
    user_settings.watch_history_source = "mdblist"
    user_settings.mdblist_api_key = api_key
    return user_settings


def rejecting_history(status: int):
    async def get_history(api_key: str):
        FakeClient._raise("/sync/watched", status)

    return get_history


def test_a_rejected_key_is_cleared_and_yields_no_history(monkeypatch):
    from app.services.profile.service import ProfileService

    cleared: list[tuple[str, str]] = []

    async def record(self, token, source):
        cleared.append((token, source))

    monkeypatch.setattr(ProfileService, "_clear_revoked_token", record)
    monkeypatch.setattr("app.services.profile.service.mdblist_service.get_history", rejecting_history(401))

    history, missing, revoked = asyncio.run(
        ProfileService().fetch_external_watch_history("mdblist", settings_with_mdblist_key("stale"), "tok_mdblist")
    )

    assert history is None
    assert revoked and not missing
    assert cleared == [("tok_mdblist", "mdblist")]


def test_an_mdblist_outage_keeps_the_key_and_yields_no_history(monkeypatch):
    from app.services.profile.service import ProfileService

    cleared: list[tuple[str, str]] = []

    async def record(self, token, source):
        cleared.append((token, source))

    monkeypatch.setattr(ProfileService, "_clear_revoked_token", record)
    monkeypatch.setattr("app.services.profile.service.mdblist_service.get_history", rejecting_history(503))

    history, missing, revoked = asyncio.run(
        ProfileService().fetch_external_watch_history("mdblist", settings_with_mdblist_key(GOOD_KEY), "tok_mdblist")
    )

    assert history is None
    assert not revoked and not missing
    assert cleared == []
