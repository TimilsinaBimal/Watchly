import asyncio

import pytest

from app.services.recommendation.catalog_service import catalog_service
from app.services.user_cache import user_cache

TOKEN = "tok_slots"


class FakeRedis:
    def __init__(self):
        self.data: dict[str, str] = {}

    async def get(self, key: str):
        return self.data.get(key)

    async def set(self, key: str, value, ttl=None):
        self.data[key] = value
        return True

    async def delete(self, key: str):
        self.data.pop(key, None)

    async def expire(self, key: str, ttl: int):
        return True

    async def delete_by_pattern(self, pattern: str):
        return 0


@pytest.fixture
def fake_redis(monkeypatch):
    fake = FakeRedis()
    for name in ("get", "set", "delete", "expire", "delete_by_pattern"):
        monkeypatch.setattr(f"app.services.user_cache.redis_service.{name}", getattr(fake, name))
    return fake


def resolve(catalog_id: str, content_type: str = "movie") -> str:
    return asyncio.run(catalog_service._resolve_slot(TOKEN, content_type, catalog_id))


def test_theme_slot_expands_to_its_stored_definition(fake_redis):
    asyncio.run(user_cache.set_row_map(TOKEN, "movie", {"theme.2": "a:g28.f:k1234.b:rshort"}))

    assert resolve("watchly.theme.2") == "watchly.theme.a:g28.f:k1234.b:rshort"


def test_item_slot_expands_to_its_seed(fake_redis):
    asyncio.run(user_cache.set_row_map(TOKEN, "movie", {"item.1": "tt0468569"}))

    assert resolve("watchly.item.1") == "watchly.item.tt0468569"


def test_the_id_survives_a_definition_change(fake_redis):
    """The whole point: an LLM rebuild or a re-randomised item seed changes what the
    row means without changing the id, so the cache key stays put."""
    asyncio.run(user_cache.set_row_map(TOKEN, "movie", {"theme.1": "a:g28"}))
    assert resolve("watchly.theme.1") == "watchly.theme.a:g28"

    asyncio.run(user_cache.set_row_map(TOKEN, "movie", {"theme.1": "a:g99.f:k77"}))
    assert resolve("watchly.theme.1") == "watchly.theme.a:g99.f:k77"


def test_slots_are_tracked_per_content_type(fake_redis):
    asyncio.run(user_cache.set_row_map(TOKEN, "movie", {"theme.1": "a:g28"}))
    asyncio.run(user_cache.set_row_map(TOKEN, "series", {"theme.1": "a:g10765"}))

    assert resolve("watchly.theme.1", "movie") == "watchly.theme.a:g28"
    assert resolve("watchly.theme.1", "series") == "watchly.theme.a:g10765"


def test_legacy_self_describing_ids_pass_through(fake_redis):
    """Manifests installed before slots carry the old ids and Stremio keeps asking
    for them until it refreshes, so they must still route."""
    asyncio.run(user_cache.set_row_map(TOKEN, "movie", {"theme.1": "a:g28"}))

    assert resolve("watchly.theme.a:g35.f:k99") == "watchly.theme.a:g35.f:k99"
    assert resolve("watchly.item.tt1375666") == "watchly.item.tt1375666"
    assert resolve("watchly.loved.tt1375666") == "watchly.loved.tt1375666"


def test_non_dynamic_ids_pass_through(fake_redis):
    assert resolve("watchly.rec") == "watchly.rec"
    assert resolve("watchly.creators") == "watchly.creators"


def test_unknown_slot_resolves_to_nothing(fake_redis):
    """A user who drops from 3 item rows to 1 still has a client asking for
    watchly.item.3. Passing the id through would make the item engine read the
    bare "3" as TMDB id 3, so an undefined slot must resolve to None instead."""
    asyncio.run(user_cache.set_row_map(TOKEN, "movie", {"item.1": "tt0468569"}))

    assert resolve("watchly.item.3") is None
    assert resolve("watchly.theme.7") is None
