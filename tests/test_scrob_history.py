import asyncio

import httpx
import pytest

from app.services.scrob import ScrobService

GOOD_KEY = "good-key"
BASE_URL = "https://scrob.example.com"

HISTORY = {
    "page": 1,
    "page_size": 100,
    "total_pages": 1,
    "total_results": 4,
    "results": [
        {
            "watched_at": "2026-01-05T22:27:00Z",
            "play_count": 1,
            "media": {"type": "movie", "tmdb_id": 949, "imdb_id": "tt0113277", "title": "Heat"},
        },
        {
            "watched_at": "2026-02-01T20:00:00Z",
            "play_count": 1,
            "media": {"type": "movie", "tmdb_id": 949, "imdb_id": "tt0113277", "title": "Heat"},
        },
        {
            "watched_at": "2025-10-15T20:00:00Z",
            "play_count": 1,
            "media": {"type": "movie", "tmdb_id": 272, "imdb_id": None, "title": "No imdb id"},
        },
        {
            "watched_at": "2025-12-24T21:00:00Z",
            "play_count": 1,
            "media": {
                "type": "episode",
                "tmdb_id": 1942,
                "show_tmdb_id": 1668,
                "show_title": "Friends",
                "title": "The One With the List",
            },
        },
    ],
}

RATINGS = {
    "results": [
        {
            "rating": 9,
            "rated_at": "2026-01-06T00:00:00Z",
            "season_number": None,
            "media": {"type": "movie", "tmdb_id": 949, "imdb_id": "tt0113277", "title": "Heat"},
        },
        {
            "rating": 7,
            "rated_at": "2025-12-01T00:00:00Z",
            "season_number": None,
            "media": {"type": "show", "tmdb_id": 5458, "imdb_id": None, "title": "The Sopranos"},
        },
        {
            "rating": 8,
            "rated_at": "2025-12-01T00:00:00Z",
            "season_number": 1,
            "media": {"type": "show", "tmdb_id": 5458, "imdb_id": None, "title": "The Sopranos"},
        },
    ]
}

TMDB_TO_IMDB = {("movie", 272): "tt0264664", ("series", 1668): "tt0108778", ("series", 5458): "tt0141842"}


class FakeTMDB:
    async def get_imdb_id(self, media_type, tmdb_id):
        return TMDB_TO_IMDB.get((media_type, tmdb_id))


class FakeClient:
    """Answers only the good key; anything else is a 401 like the real API."""

    def __init__(self, status_for_good_key: int | None = None):
        self.status_for_good_key = status_for_good_key
        self.calls: list[tuple[str, dict]] = []
        self.closed = False

    async def get(self, url, params=None, **kwargs):
        self.calls.append((url, dict(params or {})))
        if kwargs.get("headers", {}).get("X-Api-Key") != GOOD_KEY:
            self._raise(url, 401)
        if self.status_for_good_key:
            self._raise(url, self.status_for_good_key)
        if url == "/ratings":
            return RATINGS
        return HISTORY

    async def close(self):
        self.closed = True

    @staticmethod
    def _raise(url, status):
        request = httpx.Request("GET", f"{BASE_URL}{url}")
        raise httpx.HTTPStatusError("rejected", request=request, response=httpx.Response(status, request=request))


def service_with(client: FakeClient) -> ScrobService:
    service = ScrobService()
    service._client = lambda base_url: client
    return service


def test_history_merges_events_and_ratings():
    client = FakeClient()
    history = asyncio.run(service_with(client).get_history(BASE_URL, GOOD_KEY, FakeTMDB()))

    by_id = {item.imdb_id: item for item in history.items}
    assert history.source == "scrob"
    assert set(by_id) == {"tt0113277", "tt0264664", "tt0108778", "tt0141842"}
    assert client.closed

    # Two play events on one movie keep the rewatch signal.
    heat = by_id["tt0113277"]
    assert heat.type == "movie" and heat.rating == 9.0 and heat.watch_count == 2 and heat.completion == 1.0
    assert heat.last_watched is not None and heat.last_watched.year == 2026

    # TMDB-only movie resolves through TMDB.
    resolved = by_id["tt0264664"]
    assert resolved.type == "movie" and resolved.rating is None and resolved.watch_count == 1

    # Episodes collapse into their show, counted once.
    friends = by_id["tt0108778"]
    assert friends.type == "series" and friends.name == "Friends" and friends.watch_count == 1

    # A show rated but never watched still reaches the profile; its season
    # rating does not - Watchly scores at title level.
    sopranos = by_id["tt0141842"]
    assert sopranos.type == "series" and sopranos.rating == 7.0
    assert sopranos.watch_count == 0 and sopranos.completion == 0.0


def test_history_paginates():
    pages = [
        {**HISTORY, "page": 1, "total_pages": 2, "results": HISTORY["results"][:1]},
        {**HISTORY, "page": 2, "total_pages": 2, "results": HISTORY["results"][1:]},
    ]

    class PagedClient(FakeClient):
        async def get(self, url, params=None, **kwargs):
            if url == "/ratings":
                return RATINGS
            assert kwargs.get("headers", {}).get("X-Api-Key") == GOOD_KEY
            return pages[params["page"] - 1]

    history = asyncio.run(service_with(PagedClient()).get_history(BASE_URL, GOOD_KEY, FakeTMDB()))
    assert len(history.items) == 4


def test_rejected_key_raises():
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(service_with(FakeClient()).get_history(BASE_URL, "wrong-key", FakeTMDB()))


def test_probe_reaches_history_endpoint():
    client = FakeClient()
    asyncio.run(service_with(client).probe(BASE_URL, GOOD_KEY))
    assert client.calls[0][0] == "/history"
    assert client.closed


def test_account_identity_is_stable_and_not_the_key():
    a = ScrobService.account_identity(BASE_URL, GOOD_KEY)
    b = ScrobService.account_identity(BASE_URL + "/", GOOD_KEY)
    assert a == b
    assert ScrobService.account_identity(BASE_URL, "other-key") != a
    assert GOOD_KEY not in a
