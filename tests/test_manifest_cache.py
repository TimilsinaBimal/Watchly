import asyncio

import pytest

from app.core.settings import UserSettings
from app.models.library import LibraryCollection
from app.services import manifest as manifest_module
from app.services import user_cache as user_cache_module
from app.services.manifest import manifest_service
from app.services.user_cache import user_cache

TOKEN = "tok_manifest"


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


@pytest.fixture
def count_builds(monkeypatch):
    """Stub the expensive assembly, counting how often it actually runs."""
    builds: list[str] = []

    class FakeContext:
        auth_key = None
        library = LibraryCollection(source="trakt")
        user_settings = UserSettings(catalogs=[], watch_history_source="trakt", language="en-US")

        async def close(self):
            pass

    async def fake_load(token, require_auth=False):
        builds.append(token)
        return FakeContext()

    class FakeDynamicCatalogs:
        def __init__(self, **kwargs):
            pass

        async def get_dynamic_catalogs(self, library, user_settings, token=None):
            return [{"id": "watchly.theme.action", "name": "Action", "type": "movie"}]

    monkeypatch.setattr(manifest_module, "load_user_context", fake_load)
    monkeypatch.setattr(manifest_module, "DynamicCatalogService", FakeDynamicCatalogs)
    return builds


def test_second_request_is_served_from_cache(fake_redis, count_builds):
    first = asyncio.run(manifest_service.get_manifest_for_token(TOKEN))
    second = asyncio.run(manifest_service.get_manifest_for_token(TOKEN))

    assert len(count_builds) == 1
    assert first == second
    assert any("manifest" in key for key in fake_redis.data)


def test_force_rebuild_bypasses_the_cache(fake_redis, count_builds):
    """The catalog updater relies on this: its job is producing a fresh catalog
    list, so reading its own cache would make it a silent no-op."""
    asyncio.run(manifest_service.get_manifest_for_token(TOKEN))
    asyncio.run(manifest_service.get_manifest_for_token(TOKEN, force_rebuild=True))

    assert len(count_builds) == 2


def test_invalidation_forces_the_next_request_to_rebuild(fake_redis, count_builds):
    asyncio.run(manifest_service.get_manifest_for_token(TOKEN))
    asyncio.run(user_cache.invalidate_manifest(TOKEN))
    asyncio.run(manifest_service.get_manifest_for_token(TOKEN))

    assert len(count_builds) == 2


def test_cache_key_is_scoped_to_the_addon_version(fake_redis):
    """The manifest embeds the addon version, so a deploy must not keep serving a
    manifest that advertises the previous one."""
    key = user_cache._manifest_key(TOKEN)

    assert user_cache_module.__version__ in key
    assert TOKEN in key
