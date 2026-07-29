import asyncio

from app.services.trakt import HISTORY_PAGE_LIMIT, MAX_HISTORY_PAGES, TraktService


def movie_entry(n: int) -> dict:
    return {"movie": {"title": f"Film {n}", "ids": {"imdb": f"tt{1000000 + n}"}}, "plays": 1}


class FakeClient:
    """Serves a fixed number of entries using Trakt's page/limit semantics."""

    def __init__(self, total_by_url: dict[str, int], paginated: bool = True):
        self.total_by_url = total_by_url
        self.paginated = paginated
        self.calls: list[tuple[str, int]] = []

    async def get(self, url, params=None, headers=None):
        page = (params or {}).get("page", 1)
        limit = (params or {}).get("limit", HISTORY_PAGE_LIMIT)
        self.calls.append((url, page))
        total = self.total_by_url.get(url, 0)
        entries = [movie_entry(i) for i in range(total)]
        if not self.paginated:
            # Trakt's unpaginated endpoints ignore the params and return everything.
            return entries
        start = (page - 1) * limit
        return entries[start:][:limit]


def service(client) -> TraktService:
    svc = TraktService.__new__(TraktService)
    svc.client = client
    return svc


WATCHED_MOVIES = "/users/me/watched/movies"


def test_history_longer_than_one_page_is_fully_fetched():
    """The bug: only the first page came back, so a 250-title history looked like
    100 — and the watched-exclusion set was truncated to match."""
    client = FakeClient({WATCHED_MOVIES: 250})
    history = asyncio.run(service(client).get_history("token"))

    assert len(history.items) == 250
    pages = [page for url, page in client.calls if url == WATCHED_MOVIES]
    assert pages == [1, 2, 3]  # third page is short, so it stops there


def test_exact_multiple_of_the_page_size_is_fully_fetched():
    client = FakeClient({WATCHED_MOVIES: 200})
    history = asyncio.run(service(client).get_history("token"))

    assert len(history.items) == 200
    # Page 3 comes back empty, which is what ends the loop.
    assert [page for url, page in client.calls if url == WATCHED_MOVIES] == [1, 2, 3]


def test_single_short_page_costs_one_request():
    client = FakeClient({WATCHED_MOVIES: 12})
    history = asyncio.run(service(client).get_history("token"))

    assert len(history.items) == 12
    assert [page for url, page in client.calls if url == WATCHED_MOVIES] == [1]


def test_unpaginated_endpoint_does_not_loop():
    """Trakt's unpaginated endpoints ignore page params and return everything, so
    the loop must not keep asking for more of the same."""
    client = FakeClient({WATCHED_MOVIES: 250}, paginated=False)
    history = asyncio.run(service(client).get_history("token"))

    assert len(history.items) == 250
    assert [page for url, page in client.calls if url == WATCHED_MOVIES] == [1]


def test_page_cap_is_honoured():
    """A pagination contract change must not turn this into an endless loop."""
    client = FakeClient({WATCHED_MOVIES: HISTORY_PAGE_LIMIT * (MAX_HISTORY_PAGES + 5)})
    history = asyncio.run(service(client).get_history("token"))

    assert len(history.items) == HISTORY_PAGE_LIMIT * MAX_HISTORY_PAGES
    assert len([1 for url, _ in client.calls if url == WATCHED_MOVIES]) == MAX_HISTORY_PAGES


def test_a_failing_endpoint_does_not_lose_the_others():
    class PartlyBroken(FakeClient):
        async def get(self, url, params=None, headers=None):
            if "ratings" in url:
                raise RuntimeError("trakt 500")
            return await super().get(url, params=params, headers=headers)

    client = PartlyBroken({WATCHED_MOVIES: 120})
    history = asyncio.run(service(client).get_history("token"))

    assert len(history.items) == 120
