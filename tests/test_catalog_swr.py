import asyncio
import time

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

    state = {"cached": None, "age": 0, "builds": 0}

    async def fake_resolve_alias(token):
        return token

    async def fake_get_user_data(token):
        return {"settings": UserSettings(catalogs=[], watch_history_source="stremio").model_dump()}

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
    assert "max-age=60," not in headers["Cache-Control"]


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
    assert "max-age=60," in headers["Cache-Control"]  # so the client comes back soon
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
    assert "max-age=60," not in headers["Cache-Control"]
