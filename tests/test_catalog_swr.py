import asyncio
import time
from datetime import datetime, timezone

import pytest

from app.core.settings import UserSettings
from app.services.recommendation import catalog_service as cs_module
from app.services.recommendation.catalog_service import catalog_service

TOKEN = "tok_swr"
FRESH = {"metas": [{"id": "tt-fresh", "type": "movie", "name": "Fresh"}]}
STALE = {"metas": [{"id": "tt-stale", "type": "movie", "name": "Stale"}]}


class FakeRedis:
    def __init__(self):
        self.data: dict[str, str] = {}
        self.nx_calls = 0

    async def set_nx(self, key: str, value, ttl=None):
        self.nx_calls += 1
        if key in self.data:
            return False
        self.data[key] = value
        return True

    async def delete(self, key: str):
        self.data.pop(key, None)


@pytest.fixture
def harness(monkeypatch):
    """Wire the catalog service to fakes and record what it does."""
    fake_redis = FakeRedis()
    monkeypatch.setattr(cs_module.redis_service, "set_nx", fake_redis.set_nx)
    monkeypatch.setattr(cs_module.redis_service, "delete", fake_redis.delete)

    state = {"cached": None, "age": 0, "builds": 0, "refresh_due": False}

    async def fake_resolve_alias(token):
        return token

    async def fake_get_user_data(token):
        # A recent last_updated keeps the scheduled refresh from firing, so a test sees
        # the per-row path on its own unless it asks for a refresh to be due.
        last_updated = None if state["refresh_due"] else datetime.now(timezone.utc).isoformat()
        return {
            "settings": UserSettings(catalogs=[], watch_history_source="stremio").model_dump(),
            "last_updated": last_updated,
        }

    async def fake_get_catalog(token, content_type, catalog_id):
        if state["cached"] is None:
            return None
        return dict(state["cached"]), int(time.time()) - state["age"]

    async def fake_is_warming(token):
        return False

    async def fake_load_context(token, require_auth=True):
        class Ctx:
            token = TOKEN

            async def close(self):
                pass

        return Ctx()

    async def fake_build(ctx, content_type, catalog_id, headers):
        state["builds"] += 1
        # The real build does seconds of I/O. Yielding here matters: without a
        # suspension point each task would acquire and release the lock before the
        # next one started, and the dedup test would pass for the wrong reason.
        await asyncio.sleep(0.01)
        return dict(FRESH), headers

    monkeypatch.setattr(cs_module.token_store, "resolve_alias", fake_resolve_alias)
    monkeypatch.setattr(cs_module.token_store, "get_user_data", fake_get_user_data)
    monkeypatch.setattr(cs_module.user_cache, "get_catalog", fake_get_catalog)
    monkeypatch.setattr(cs_module.warmup_service, "is_warming", fake_is_warming)
    monkeypatch.setattr(cs_module, "load_user_context", fake_load_context)
    monkeypatch.setattr(catalog_service, "_build_catalog", fake_build)
    state["redis"] = fake_redis
    return state


def get(content_type="movie", catalog_id="watchly.rec"):
    return asyncio.run(catalog_service.get_catalog(TOKEN, content_type, catalog_id))


def test_fresh_cache_is_served_without_building(harness):
    harness["cached"] = FRESH
    harness["age"] = 60

    data, headers = get()

    assert data["metas"][0]["id"] == "tt-fresh"
    assert harness["builds"] == 0


def test_stale_cache_is_served_immediately(harness):
    """The regression this fixes: a stale row used to rebuild on the request, so
    every row on a home screen stalled once a day."""
    harness["cached"] = STALE
    harness["age"] = 10**6  # well past the refresh interval

    async def scenario():
        data, headers = await catalog_service.get_catalog(TOKEN, "movie", "watchly.rec")
        # The refresh runs as a background task; let it finish before asserting.
        await asyncio.sleep(0)
        await asyncio.gather(*list(catalog_service._refresh_tasks))
        return data, headers

    data, headers = asyncio.run(scenario())

    assert data["metas"][0]["id"] == "tt-stale"  # served the stale body, not a rebuild
    assert harness["builds"] == 1  # and the rebuild did happen, behind the response


def test_concurrent_requests_trigger_one_refresh(harness):
    """Stremio asks for every enabled row at once, so the lock has to be in Redis
    rather than in-process."""
    harness["cached"] = STALE
    harness["age"] = 10**6

    async def scenario():
        await asyncio.gather(*(catalog_service.get_catalog(TOKEN, "movie", "watchly.rec") for _ in range(5)))
        await asyncio.sleep(0)
        await asyncio.gather(*list(catalog_service._refresh_tasks))

    asyncio.run(scenario())

    assert harness["redis"].nx_calls == 5  # all five tried
    assert harness["builds"] == 1  # only one won


def test_cold_cache_builds_on_the_request(harness):
    harness["cached"] = None

    data, headers = get()

    assert data["metas"][0]["id"] == "tt-fresh"
    assert harness["builds"] == 1


def test_client_cache_window_stays_short(harness):
    """Served ids are stable slots now, so this header is the only thing telling a
    client a row's content moved. It was 12h back when churning ids busted client
    caches by accident."""
    harness["cached"] = FRESH
    harness["age"] = 60

    _, headers = get()

    assert "max-age=60," in headers["Cache-Control"]
    assert "stale-while-revalidate=3600" in headers["Cache-Control"]


def refresh_due_while_stale(harness, monkeypatch, refresh_rebuilds_the_row: bool) -> int:
    """Open a stale row whose request also starts the scheduled refresh; return how many
    times the row was built after the refresh finished."""
    harness["cached"] = STALE
    harness["age"] = 10**6
    harness["refresh_due"] = True
    release = asyncio.Event()

    async def scheduled_refresh(token, credentials, update_timestamp=True):
        await release.wait()
        if refresh_rebuilds_the_row:
            harness["age"] = 0
        return True

    monkeypatch.setattr(cs_module.catalog_updater, "refresh_catalogs_for_credentials", scheduled_refresh)

    async def scenario():
        data, _ = await catalog_service.get_catalog(TOKEN, "movie", "watchly.rec")
        assert data["metas"][0]["id"] == "tt-stale"
        await asyncio.sleep(0.05)
        builds_during_refresh = harness["builds"]
        release.set()
        await asyncio.gather(*list(cs_module.catalog_updater._pending_tasks))
        await asyncio.gather(*list(catalog_service._refresh_tasks))
        assert builds_during_refresh == 0
        return harness["builds"]

    return asyncio.run(scenario())


def test_stale_row_waits_for_a_scheduled_refresh_that_rebuilds_it(harness, monkeypatch):
    """The request that starts the scheduled refresh usually finds its row stale too. A
    rebuild running alongside the refresh uses the library and profiles it is replacing,
    and could land after the refresh as fresh."""
    assert refresh_due_while_stale(harness, monkeypatch, refresh_rebuilds_the_row=True) == 0


def test_stale_row_is_rebuilt_after_a_refresh_that_leaves_it(harness, monkeypatch):
    """Not every refresh replaces the library: Trakt and Simkl users, a failed fetch, or
    an install missing from the Stremio collection leave the row stale."""
    assert refresh_due_while_stale(harness, monkeypatch, refresh_rebuilds_the_row=False) == 1
