import asyncio
import json

import httpx
import pytest

from app.core.settings import get_default_settings
from app.services.nuvio import NuvioService
from app.services.profile.service import ProfileService
from app.services.token_store import token_store

GOOD_TOKEN = "good-access"
TOKEN = "tok_nuvio_history"


def watched_row(content_id: str, content_type: str, watched_at: int, **extra) -> dict:
    return {
        "content_id": content_id,
        "content_type": content_type,
        "title": content_id,
        "watched_at": watched_at,
        **extra,
    }


def progress_row(content_id: str, position: int) -> dict:
    return {
        "content_id": content_id,
        "content_type": "movie",
        "position": position,
        "duration": 7_920_000,
        "last_watched": 1767670000000,
    }


WATCHED = [
    watched_row("tt0113277", "movie", 1767650000000),
    watched_row("tmdb:1396", "series", 1767640000000, season=1, episode=1),
    watched_row("tmdb:1396", "series", 1767660000000, season=1, episode=2),
    watched_row("kitsu:1", "series", 1767660000000),
]
PROGRESS = [progress_row("tmdb:550", 7_200_000), progress_row("tmdb:999", 600_000)]


def rejection(url: str, status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", f"https://api.nuvio.tv{url}")
    return httpx.HTTPStatusError("rejected", request=request, response=httpx.Response(status, request=request))


class FakeNuvioClient:
    """Answers only the good session; anything else is a 401 like the real API."""

    def __init__(self, status_for_good_token: int | None = None):
        self.status_for_good_token = status_for_good_token

    async def post(self, url: str, json=None, headers=None, **kwargs):
        if headers.get("Authorization") != f"Bearer {GOOD_TOKEN}":
            raise rejection(url, 401)
        if self.status_for_good_token:
            raise rejection(url, self.status_for_good_token)
        assert json["p_profile_id"] == 2
        return WATCHED if url.endswith("sync_pull_watched_items") else PROGRESS


class FakeTMDB:
    async def get_imdb_id(self, media_type: str, tmdb_id: int):
        return {("series", 1396): "tt0903747", ("movie", 550): "tt0137523"}.get((media_type, tmdb_id))


def nuvio_with(client: FakeNuvioClient) -> NuvioService:
    service = NuvioService()
    service.client = client
    return service


def test_history_merges_watched_and_finished_progress_and_resolves_tmdb_ids():
    history = asyncio.run(nuvio_with(FakeNuvioClient()).get_history(GOOD_TOKEN, 2, FakeTMDB()))

    by_id = {item.imdb_id: item for item in history.items}
    assert history.source == "nuvio"
    assert set(by_id) == {"tt0113277", "tt0903747", "tt0137523"}

    series = by_id["tt0903747"]
    assert series.type == "series" and series.completion == 1.0
    assert series.last_watched is not None and int(series.last_watched.timestamp() * 1000) == 1767660000000

    finished = by_id["tt0137523"]
    assert finished.type == "movie" and finished.completion >= 0.9
    assert all(item.rating is None for item in history.items)


def test_a_rejected_session_raises_instead_of_an_empty_history():
    with pytest.raises(httpx.HTTPStatusError) as exc:
        asyncio.run(nuvio_with(FakeNuvioClient()).get_history("stale", 2, FakeTMDB()))
    assert exc.value.response.status_code == 401


class FakeRedis:
    def __init__(self):
        self.data: dict[str, str] = {}

    async def get(self, key):
        return self.data.get(key)

    async def set(self, key, value, ttl=None):
        self.data[key] = value
        return True

    async def set_nx(self, key, value, ttl=None):
        if key in self.data:
            return False
        self.data[key] = str(value)
        return True

    async def exists(self, key):
        return key in self.data

    async def delete(self, key):
        self.data.pop(key, None)


@pytest.fixture
def account(monkeypatch):
    fake = FakeRedis()
    for name in ("get", "set", "delete"):
        monkeypatch.setattr(f"app.services.token_store.redis_service.{name}", getattr(fake, name))
    for name in ("set_nx", "exists", "delete"):
        monkeypatch.setattr(f"app.services.profile.service.redis_service.{name}", getattr(fake, name))
    monkeypatch.setattr("app.services.token_store.settings.TOKEN_SALT", "unit-test-salt")

    async def noop(token):
        return None

    monkeypatch.setattr("app.services.token_store.user_cache.invalidate_all_user_data", noop)
    token_store._get_user_data_cached.cache_clear()

    settings = get_default_settings()
    settings.watch_history_source = "nuvio"
    settings.nuvio_access_token = "expired-access"
    settings.nuvio_refresh_token = "refresh-1"
    settings.nuvio_expires_at = 1
    settings.nuvio_profile_id = 2
    settings.tmdb_api_key = "tmdb-key"
    fake.data[f"watchly:token:{TOKEN}"] = json.dumps({"settings": settings.model_dump(), "last_updated": "2026-01-01"})

    cleared: list[tuple[str, str]] = []

    async def record(self, token, source):
        cleared.append((token, source))

    monkeypatch.setattr(ProfileService, "_clear_revoked_token", record)
    monkeypatch.setattr("app.services.profile.service.get_tmdb_service", lambda **kwargs: FakeTMDB())
    return fake, settings, cleared


async def stored_settings() -> dict:
    """What the account holds now, decrypted; the raw blob is ciphertext."""
    token_store._get_user_data_cached.cache_clear()
    return (await token_store.get_user_data(TOKEN))["settings"]


def install_refresh(monkeypatch, outcome):
    calls = []

    async def refresh(refresh_token):
        calls.append(refresh_token)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr("app.services.profile.service.nuvio_service.refresh", refresh)
    return calls


def test_concurrent_fetches_refresh_once_and_persist_the_rotated_pair(monkeypatch, account):
    fake, settings, cleared = account
    calls = install_refresh(monkeypatch, {"access_token": GOOD_TOKEN, "refresh_token": "refresh-2", "expires_in": 3600})
    monkeypatch.setattr("app.services.profile.service.nuvio_service.client", FakeNuvioClient())

    async def both():
        service = ProfileService()
        return await asyncio.gather(
            service.fetch_external_watch_history("nuvio", settings.model_copy(), TOKEN),
            service.fetch_external_watch_history("nuvio", settings.model_copy(), TOKEN),
        )

    results = asyncio.run(both())

    assert calls == ["refresh-1"]
    assert all(history is not None and len(history.items) == 3 for history, _, _ in results)
    assert all(not revoked for _, _, revoked in results)
    stored = asyncio.run(stored_settings())
    assert stored["nuvio_access_token"] == GOOD_TOKEN and stored["nuvio_refresh_token"] == "refresh-2"
    assert cleared == []


def test_a_failed_refresh_keeps_the_session(monkeypatch, account):
    fake, settings, cleared = account
    install_refresh(monkeypatch, rejection("/auth/v1/token", 400))

    history, missing, revoked = asyncio.run(ProfileService().fetch_external_watch_history("nuvio", settings, TOKEN))

    assert history is None and not missing and not revoked
    assert cleared == []
    assert asyncio.run(stored_settings())["nuvio_refresh_token"] == "refresh-1"


def test_a_session_rejected_after_a_refresh_is_cleared(monkeypatch, account):
    fake, settings, cleared = account
    install_refresh(monkeypatch, {"access_token": GOOD_TOKEN, "refresh_token": "refresh-2", "expires_in": 3600})
    monkeypatch.setattr("app.services.profile.service.nuvio_service.client", FakeNuvioClient(status_for_good_token=401))

    history, missing, revoked = asyncio.run(ProfileService().fetch_external_watch_history("nuvio", settings, TOKEN))

    assert history is None and not missing and revoked
    assert cleared == [(TOKEN, "nuvio")]


def test_an_outage_yields_no_history_and_keeps_the_session(monkeypatch, account):
    fake, settings, cleared = account
    install_refresh(monkeypatch, {"access_token": GOOD_TOKEN, "refresh_token": "refresh-2", "expires_in": 3600})
    monkeypatch.setattr("app.services.profile.service.nuvio_service.client", FakeNuvioClient(status_for_good_token=503))

    history, missing, revoked = asyncio.run(ProfileService().fetch_external_watch_history("nuvio", settings, TOKEN))

    assert history is None and not missing and not revoked
    assert cleared == []
