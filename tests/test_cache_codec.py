import asyncio
import json

import pytest

from app.models.library import LibraryCollection, StremioLibraryItem
from app.services import cache_codec
from app.services.user_cache import user_cache

TOKEN = "tok_codec"


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


@pytest.fixture
def fake_redis(monkeypatch):
    fake = FakeRedis()
    for name in ("get", "set", "delete", "expire"):
        monkeypatch.setattr(f"app.services.user_cache.redis_service.{name}", getattr(fake, name))
    return fake


def big_library(count: int = 400) -> LibraryCollection:
    return LibraryCollection(
        watched=[
            StremioLibraryItem(
                _id=f"tt{1000000 + i}",
                type="movie",
                name=f"A Film With A Reasonably Long Title {i}",
                temp=False,
                removed=False,
            )
            for i in range(count)
        ],
        source="stremio",
    )


def test_round_trip():
    payload = json.dumps({"metas": [{"id": f"tt{i}", "name": "x" * 40} for i in range(100)]})
    assert cache_codec.decode(cache_codec.encode(payload)) == payload


def test_small_values_are_left_alone():
    """zlib's header plus base64 overhead makes short payloads bigger, not smaller."""
    payload = '{"a": 1}'
    assert cache_codec.encode(payload) == payload


def test_large_values_shrink_substantially():
    payload = big_library().model_dump_json(by_alias=True)
    encoded = cache_codec.encode(payload)

    assert encoded.startswith("z1:")
    assert len(encoded) < len(payload) / 3, f"{len(payload)}B -> {len(encoded)}B is a poor ratio"


def test_legacy_uncompressed_values_still_read():
    """No key migration: values written before compression have no prefix and must
    decode as the plain JSON they are."""
    payload = json.dumps({"metas": []})
    assert cache_codec.decode(payload) == payload


def test_corrupt_payload_is_treated_as_a_miss():
    """Returning the raw value lets the caller's JSON parse fail and report a miss,
    rather than every call site growing zlib and base64 handlers."""
    assert cache_codec.decode("z1:not-valid-base64!!") == "z1:not-valid-base64!!"


def test_library_survives_a_cache_round_trip(fake_redis):
    library = big_library(50)

    asyncio.run(user_cache.set_library_items(TOKEN, library))
    stored = fake_redis.data[f"watchly:library_items:{TOKEN}"]
    restored = asyncio.run(user_cache.get_library_items(TOKEN))

    assert stored.startswith("z1:")  # actually stored compressed
    assert len(restored.watched) == 50
    assert restored.source == "stremio"
    assert {i.id for i in restored.watched} == {i.id for i in library.watched}


def test_catalog_survives_a_cache_round_trip(fake_redis):
    catalog = {"metas": [{"id": f"tt{i}", "type": "movie", "name": "x" * 60} for i in range(40)]}

    asyncio.run(user_cache.set_catalog(TOKEN, "movie", "watchly.rec", catalog))
    stored = fake_redis.data[f"watchly:catalog:{TOKEN}:movie:watchly.rec"]
    restored, created_at = asyncio.run(user_cache.get_catalog(TOKEN, "movie", "watchly.rec"))

    assert stored.startswith("z1:")
    assert restored == catalog
    assert created_at > 0


def test_legacy_plain_json_catalog_still_reads(fake_redis):
    """A value written by the previous release must keep working after deploy."""
    catalog = {"metas": [{"id": "tt1", "type": "movie", "name": "Example"}]}
    fake_redis.data[f"watchly:catalog:{TOKEN}:movie:watchly.rec"] = json.dumps(
        {"data": catalog, "created_at": 1700000000}
    )

    restored, created_at = asyncio.run(user_cache.get_catalog(TOKEN, "movie", "watchly.rec"))

    assert restored == catalog
    assert created_at == 1700000000
