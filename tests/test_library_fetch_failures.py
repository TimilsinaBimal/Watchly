import asyncio

import httpx
import pytest

from app.core.settings import get_default_settings
from app.models.library import LibraryCollection, StremioLibraryItem
from app.services import manifest as manifest_module
from app.services.manifest import manifest_service
from app.services.stremio.library import StremioLibraryService
from app.services.user_cache import user_cache

TOKEN = "tok_fetch_failures"


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


class StremioReturning:
    def __init__(self, body):
        self.body = body

    async def post(self, path, json=None):
        return self.body


class UnreachableStremio:
    async def post(self, path, json=None):
        raise httpx.ConnectError("connection refused")


class NoLikes:
    async def get(self, path):
        return {"metas": []}


def test_unreachable_stremio_is_not_an_empty_library():
    """An unreachable Stremio API has to be distinguishable from a user with nothing
    watched, or the caller caches an empty library over the real one."""
    service = StremioLibraryService(UnreachableStremio(), NoLikes())

    assert asyncio.run(service.get_library_items("auth-key")) is None


@pytest.mark.parametrize(
    "body", [{"error": {"message": "Session not found", "code": 1}}, {}], ids=["error-body", "empty-body"]
)
def test_datastore_error_response_is_not_an_empty_library(body):
    """Stremio reports a rejected authKey in a 200 body, and the client turns an empty or
    non-JSON 2xx into {}. Neither is a user with nothing watched."""
    service = StremioLibraryService(StremioReturning(body), NoLikes())

    assert asyncio.run(service.get_library_items("auth-key")) is None


def test_an_empty_library_is_still_a_library():
    service = StremioLibraryService(StremioReturning({"result": []}), NoLikes())

    library = asyncio.run(service.get_library_items("auth-key"))

    assert library is not None and library.is_empty()


def test_failed_fetch_keeps_the_cached_library(fake_redis, monkeypatch):
    cached = LibraryCollection(
        watched=[StremioLibraryItem(_id="tt0000001", type="movie", name="Cached", temp=False, removed=False)]
    )
    asyncio.run(user_cache.set_library_items(TOKEN, cached))
    profile_builds = []

    class RecordingProfileService:
        def __init__(self, *args, **kwargs):
            pass

        async def build_and_cache_profile(self, token, content_type, *args, **kwargs):
            profile_builds.append(content_type)
            return None, set(), set()

    async def failed_fetch(source, user_settings, token, bundle, auth_key):
        return None

    monkeypatch.setattr(manifest_module, "fetch_library_for_source", failed_fetch)
    monkeypatch.setattr(manifest_module, "ProfileService", RecordingProfileService)

    asyncio.run(
        manifest_service.cache_library_and_profiles(
            bundle=object(), auth_key="auth-key", user_settings=get_default_settings(), token=TOKEN
        )
    )

    library = asyncio.run(user_cache.get_library_items(TOKEN))
    assert [i.id for i in library.all_items()] == ["tt0000001"]
    assert profile_builds == []


def test_failed_likes_fetch_is_not_a_library_without_loves():
    """Loved and liked titles come from a second API. Built without them, the library
    drops every loved-only title and demotes the rest, and cached that way the loved
    rows go blank and loved titles can be recommended again."""

    class LikesDown:
        async def get(self, path):
            raise httpx.ConnectError("connection refused")

    service = StremioLibraryService(StremioReturning({"result": []}), LikesDown())

    assert asyncio.run(service.get_library_items("auth-key")) is None
