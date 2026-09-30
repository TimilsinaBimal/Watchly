import asyncio
import time

import pytest

import app.services.profile.service as profile_module
import app.services.token_store as token_store_module
from app.core.settings import get_default_settings
from app.services import nuvio as nuvio_module
from app.services.nuvio import NuvioService, is_expiring
from app.services.profile.service import ProfileService


class FakeNuvioService(NuvioService):
    """NuvioService with the RPC layer replaced by canned rows."""

    def __init__(self, progress=None, watched=None, page_size=None):
        self.progress = progress or []
        self.watched = watched or []
        self.page_size = page_size
        self.rpc_calls = []

    async def _rpc(self, function, params, access_token):
        self.rpc_calls.append((function, params))
        if function == "sync_pull_watch_progress":
            return self.progress
        if function == "sync_pull_watched_items":
            page = params.get("p_page", 1)
            size = params.get("p_page_size")
            start = (page - 1) * size
            return self.watched[start : start + size]
        raise AssertionError(f"unexpected rpc {function}")


class FakeTmdbService:
    """Resolves only the ids it knows, the way TMDB answers for a missing mapping."""

    def __init__(self, mapping):
        self.mapping = mapping
        self.lookups = []

    async def get_imdb_id(self, media_type, tmdb_id):
        self.lookups.append((media_type, tmdb_id))
        return self.mapping.get((media_type, tmdb_id))


def progress_row(content_id, content_type, position, duration, last_watched, **extra):
    return {
        "content_id": content_id,
        "content_type": content_type,
        "position": position,
        "duration": duration,
        "last_watched": last_watched,
        **extra,
    }


def watched_row(content_id, content_type, title, watched_at, **extra):
    return {
        "content_id": content_id,
        "content_type": content_type,
        "title": title,
        "watched_at": watched_at,
        **extra,
    }


def test_watch_history_merges_progress_and_watched_items():
    service = FakeNuvioService(
        progress=[
            progress_row("tt100", "movie", 9000, 10000, 1_700_000_000_000),
            # Started and abandoned — the watched list, not a progress row, decides this.
            progress_row("tt200", "movie", 100, 10000, 1_700_000_000_000),
            progress_row("tt300", "series", 4_000_000, 4_000_000, 1_600_000_000_000, season=1, episode=1),
            progress_row("tt300", "series", 1_000_000, 4_000_000, 1_655_000_000_000, season=1, episode=2),
            progress_row("home", "channel", 5, 10, 1_600_000_000_000),
        ],
        watched=[
            watched_row("tt200", "movie", "Finished Later", 1_700_000_500_000),
            watched_row("tt400", "tv", "Series Via TV Type", 1_700_000_600_000),
            watched_row("tt100", "movie", "Movie", 1_650_000_000_000),
        ],
    )

    history = asyncio.run(service.get_watch_history("session", 1))
    by_id = {item.imdb_id: item for item in history.items}

    assert history.source == "nuvio"
    assert set(by_id) == {"tt100", "tt200", "tt300", "tt400"}
    assert by_id["tt100"].completion == pytest.approx(0.9)
    assert by_id["tt100"].name == "Movie"
    # The app's own watched list is the authority for what counts as watched.
    assert by_id["tt200"].completion == 1.0
    assert by_id["tt200"].name == "Finished Later"
    # Episodes fold into one title: best completion, latest watch.
    assert by_id["tt300"].completion == 1.0
    assert by_id["tt300"].type == "series"
    assert by_id["tt300"].last_watched == nuvio_module._timestamp(1_655_000_000_000)
    # `tv` is a series in Watchly's vocabulary.
    assert by_id["tt400"].type == "series"
    assert all(item.rating is None for item in history.items)
    assert all(item.watch_count == 1 for item in history.items)


def test_tmdb_ids_resolve_and_unsupported_prefixes_are_skipped(monkeypatch):
    fake_tmdb = FakeTmdbService({("movie", 550): "tt0137523"})
    monkeypatch.setattr("app.services.tmdb.service.get_tmdb_service", lambda **kwargs: fake_tmdb)

    service = FakeNuvioService(
        watched=[
            watched_row("tmdb:550", "movie", "Fight Club", 1_700_000_000_000),
            watched_row("kitsu:12345", "series", "Anime", 1_700_000_000_000),
            watched_row("tmdb:999999999", "movie", "No IMDb Mapping", 1_700_000_000_000),
        ]
    )

    history = asyncio.run(service.get_watch_history("session", 1, tmdb_api_key="tmdb-key"))

    assert [item.imdb_id for item in history.items] == ["tt0137523"]
    assert history.items[0].name == "Fight Club"
    assert fake_tmdb.lookups == [("movie", 550), ("movie", 999999999)]


def test_tmdb_ids_are_dropped_without_a_key(monkeypatch):
    def explode(**kwargs):
        raise AssertionError("no TMDB lookup without an api key")

    monkeypatch.setattr("app.services.tmdb.service.get_tmdb_service", explode)

    service = FakeNuvioService(watched=[watched_row("tmdb:550", "movie", "Fight Club", 1_700_000_000_000)])
    history = asyncio.run(service.get_watch_history("session", 1))

    assert history.items == []


def test_watched_items_pull_walks_every_page(monkeypatch):
    monkeypatch.setattr(nuvio_module, "WATCHED_ITEMS_PAGE_SIZE", 2)
    rows = [watched_row(f"tt{index}", "movie", f"Title {index}", 1_700_000_000_000 + index) for index in range(5)]

    service = FakeNuvioService(watched=rows)
    history = asyncio.run(service.get_watch_history("session", 1))

    assert len(history.items) == 5
    pages = [params["p_page"] for function, params in service.rpc_calls if function == "sync_pull_watched_items"]
    # 5 rows at 2 per page: three full-ish pages, stopping on the short one.
    assert pages == [1, 2, 3]


class RecordingNuvio:
    """Stand-in for the module singleton, counting refresh calls."""

    def __init__(self, result):
        self.result = result
        self.calls = 0

    async def refresh(self, refresh_token):
        self.calls += 1
        return self.result


class FakeTokenStore:
    def __init__(self, data=None):
        self.data = data or {}

    async def get_user_data(self, token):
        return self.data.get(token)

    async def update_user_data(self, token, payload):
        self.data[token] = payload
        return token


def nuvio_settings(access_token, refresh_token, expires_at):
    settings = get_default_settings()
    settings.nuvio_access_token = access_token
    settings.nuvio_refresh_token = refresh_token
    settings.nuvio_expires_at = expires_at
    return settings


def test_nuvio_token_is_refreshed_only_when_expiring(monkeypatch):
    store = FakeTokenStore({"tok": {"settings": {}}})
    monkeypatch.setattr(token_store_module, "token_store", store)

    fake_nuvio = RecordingNuvio({"access_token": "fresh", "refresh_token": "r2", "expires_in": 3600})
    monkeypatch.setattr(profile_module, "nuvio_service", fake_nuvio)

    service = ProfileService.__new__(ProfileService)

    live = nuvio_settings("live", "r1", int(time.time()) + 3600)
    assert asyncio.run(service._ensure_nuvio_token_fresh("tok", live)) == "live"
    assert fake_nuvio.calls == 0

    expired = nuvio_settings("stale", "r1", int(time.time()) - 5)
    assert asyncio.run(service._ensure_nuvio_token_fresh("tok", expired)) == "fresh"
    assert fake_nuvio.calls == 1
    assert store.data["tok"]["settings"]["nuvio_access_token"] == "fresh"
    assert store.data["tok"]["settings"]["nuvio_refresh_token"] == "r2"


def test_failed_refresh_keeps_the_usable_token(monkeypatch):
    store = FakeTokenStore({"tok": {"settings": {}}})
    monkeypatch.setattr(token_store_module, "token_store", store)

    fake_nuvio = RecordingNuvio(None)
    monkeypatch.setattr(profile_module, "nuvio_service", fake_nuvio)

    service = ProfileService.__new__(ProfileService)
    expired = nuvio_settings("stale", "r1", int(time.time()) - 5)

    # The old token is still returned so the fetch can surface the real failure,
    # and nothing was written over the stored session.
    assert asyncio.run(service._ensure_nuvio_token_fresh("tok", expired)) == "stale"
    assert store.data["tok"]["settings"] == {}

    # No refresh token at all (or no account token to write against) means no attempt.
    assert asyncio.run(service._ensure_nuvio_token_fresh(None, expired)) == "stale"
    assert fake_nuvio.calls == 1


def test_watched_items_pull_stops_at_the_page_cap(monkeypatch):
    # Full pages look like "more to come", so a contract change would loop forever.
    monkeypatch.setattr(nuvio_module, "WATCHED_ITEMS_PAGE_SIZE", 2)
    monkeypatch.setattr(nuvio_module, "MAX_WATCHED_ITEMS_PAGES", 2)

    service = FakeNuvioService(
        watched=[watched_row(f"tt{index}", "movie", f"Movie {index}", 1_700_000_000_000) for index in range(6)]
    )

    rows = asyncio.run(service._pull_watched_items("session", 1))

    assert len(rows) == 4
    assert [params["p_page"] for _, params in service.rpc_calls] == [1, 2]


def test_expiry_window():
    assert is_expiring(None) is True
    assert is_expiring(0) is True
    assert is_expiring(int(time.time()) + 30) is True
    assert is_expiring(int(time.time()) + 3600) is False
