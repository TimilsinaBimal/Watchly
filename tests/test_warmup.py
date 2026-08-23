import asyncio

import pytest

from app.core.settings import UserSettings
from app.models.library import LibraryCollection, StremioLibraryItem
from app.services import warmup as warmup_module
from app.services.warmup import warmup_service

TOKEN = "tok_warm"


class FakeRedis:
    def __init__(self):
        self.data: dict[str, str] = {}

    async def get(self, key: str):
        return self.data.get(key)

    async def set(self, key: str, value, ttl=None):
        self.data[key] = value
        return True

    async def set_nx(self, key: str, value, ttl=None):
        if key in self.data:
            return False
        self.data[key] = value
        return True

    async def delete(self, key: str):
        self.data.pop(key, None)

    async def exists(self, key: str):
        return key in self.data


@pytest.fixture
def fake_redis(monkeypatch):
    fake = FakeRedis()
    for name in ("get", "set", "set_nx", "delete", "exists"):
        monkeypatch.setattr(f"app.services.warmup.redis_service.{name}", getattr(fake, name))
    return fake


@pytest.fixture
def stub_work(monkeypatch):
    """Replace the expensive steps, recording the order they ran in."""
    steps: list[str] = []

    class FakeManifest:
        async def cache_library_and_profiles(self, bundle, auth_key, user_settings, token):
            steps.append("profiles")
            return LibraryCollection(
                watched=[
                    StremioLibraryItem(_id="tt1", type="movie", name="A", temp=False, removed=False),
                    StremioLibraryItem(_id="tt2", type="movie", name="B", temp=False, removed=False),
                ],
                source="stremio",
            )

        async def get_manifest_for_token(self, token, force_rebuild=False):
            steps.append(f"manifest(force={force_rebuild})")
            return {"catalogs": []}

    class FakeCatalogs:
        async def get_catalog(self, token, content_type, catalog_id):
            steps.append(f"catalog:{content_type}:{catalog_id}")
            return {"metas": []}, {}

    class FakeBundle:
        async def close(self):
            pass

    monkeypatch.setattr("app.services.manifest.manifest_service", FakeManifest())
    monkeypatch.setattr("app.services.recommendation.catalog_service.catalog_service", FakeCatalogs())
    monkeypatch.setattr(warmup_module, "StremioBundle", FakeBundle)
    return steps


def settings() -> UserSettings:
    return UserSettings(catalogs=[], watch_history_source="stremio")


def test_prime_walks_the_states_to_ready(fake_redis, stub_work):
    asyncio.run(warmup_service.prime(TOKEN, "authkey", settings()))

    assert asyncio.run(warmup_service.get_status(TOKEN))["state"] == "ready"
    assert stub_work == [
        "profiles",
        "manifest(force=True)",
        "catalog:movie:watchly.rec",
        "catalog:series:watchly.rec",
    ]


def test_status_carries_detail_for_the_progress_line(fake_redis, stub_work):
    """The page shows something concrete rather than a bare spinner."""
    seen: list[dict] = []
    original = warmup_service._set_status

    async def record(token, state, detail=None):
        await original(token, state, detail)
        seen.append(await warmup_service.get_status(token))

    warmup_service._set_status = record
    try:
        asyncio.run(warmup_service.prime(TOKEN, "authkey", settings()))
    finally:
        warmup_service._set_status = original

    states = [s["state"] for s in seen]
    assert states == ["building_profile", "profile_ready", "warming_manifest", "warming_catalogs", "ready"]
    assert seen[1]["detail"] == "2 items in your library"


def test_a_second_warm_is_skipped_while_one_holds_the_lock(fake_redis, stub_work):
    async def scenario():
        await warmup_service._set_status(TOKEN, "pending")
        # Simulate a warm already in flight by taking the lock first.
        await fake_redis.set_nx(f"watchly:warmlock:{TOKEN}", "1", 900)
        await warmup_service.prime(TOKEN, "authkey", settings())

    asyncio.run(scenario())

    assert stub_work == []
    assert asyncio.run(warmup_service.get_status(TOKEN))["state"] == "pending"


def test_failure_reports_error_and_frees_the_lock(fake_redis, stub_work, monkeypatch):
    class Boom:
        async def cache_library_and_profiles(self, *args, **kwargs):
            raise RuntimeError("trakt is down")

    monkeypatch.setattr("app.services.manifest.manifest_service", Boom())

    asyncio.run(warmup_service.prime(TOKEN, "authkey", settings()))

    assert asyncio.run(warmup_service.get_status(TOKEN))["state"] == "error"
    # Lock released, so a later attempt can retry rather than being locked out.
    assert not asyncio.run(warmup_service.is_warming(TOKEN))


def test_unknown_token_reports_unknown(fake_redis):
    assert asyncio.run(warmup_service.get_status("never-warmed"))["state"] == "unknown"


def test_is_warming_tracks_the_lock(fake_redis, stub_work):
    assert not asyncio.run(warmup_service.is_warming(TOKEN))

    async def check_during_warm():
        state = {}

        class Watcher:
            async def cache_library_and_profiles(self, *args, **kwargs):
                state["warming"] = await warmup_service.is_warming(TOKEN)
                return LibraryCollection(source="stremio")

            async def get_manifest_for_token(self, token, force_rebuild=False):
                return {}

        import app.services.manifest as manifest_mod

        original = manifest_mod.manifest_service
        manifest_mod.manifest_service = Watcher()
        try:
            await warmup_service.prime(TOKEN, None, settings())
        finally:
            manifest_mod.manifest_service = original
        return state["warming"]

    assert asyncio.run(check_during_warm()) is True
    assert not asyncio.run(warmup_service.is_warming(TOKEN))


def test_create_token_returns_without_waiting_for_the_warm(monkeypatch):
    """The whole point: the browser gets its manifest URL before any library fetch.

    The warm is stubbed to block forever, so if the endpoint awaited it this test
    would hang rather than fail.
    """
    from fastapi.testclient import TestClient

    from app.api.models.tokens import TokenResponse
    from app.core.app import app

    async def fake_create(payload):
        return (
            TokenResponse(token="tok_abc", manifestUrl="http://host/tok_abc/manifest.json"),
            "authkey",
            settings(),
        )

    monkeypatch.setattr("app.api.endpoints.tokens.auth_service.create_user_token", fake_create)

    enqueued: list[str] = []
    never_finishes = asyncio.Event()

    async def blocking_prime(token, auth_key, user_settings):
        await never_finishes.wait()

    async def noop_pending(token):
        return None

    monkeypatch.setattr(warmup_service, "prime", blocking_prime)
    monkeypatch.setattr(warmup_service, "mark_pending", noop_pending)
    monkeypatch.setattr(warmup_service, "enqueue", lambda token, auth_key, user_settings: enqueued.append(token))

    response = TestClient(app).post("/tokens/", json={"watch_history_source": "stremio"})

    assert response.status_code == 200
    assert response.json()["manifestUrl"] == "http://host/tok_abc/manifest.json"
    assert enqueued == ["tok_abc"]
