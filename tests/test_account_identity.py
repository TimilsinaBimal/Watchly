import asyncio
import json

import pytest
from fastapi import HTTPException

from app.api.models.tokens import TokenRequest
from app.services.auth import AuthService
from app.services.token_store import token_store


class FakeRedis:
    def __init__(self):
        self.data: dict[str, str] = {}

    async def get(self, key: str):
        return self.data.get(key)

    async def set(self, key: str, value: str, ttl=None):
        self.data[key] = value
        return True

    async def delete(self, key: str):
        self.data.pop(key, None)


def setup_fakes(monkeypatch, stremio_identity=None):
    """Wire token_store to an in-memory redis and stub provider verification."""
    fake = FakeRedis()
    monkeypatch.setattr("app.services.token_store.redis_service.get", fake.get)
    monkeypatch.setattr("app.services.token_store.redis_service.set", fake.set)
    monkeypatch.setattr("app.services.token_store.redis_service.delete", fake.delete)
    monkeypatch.setattr("app.services.token_store.settings.TOKEN_SALT", "unit-test-salt")

    async def noop_invalidate(token):
        return None

    monkeypatch.setattr("app.services.token_store.user_cache.invalidate_all_user_data", noop_invalidate)
    token_store._get_user_data_cached.cache_clear()

    async def fake_stremio(self, payload):
        if stremio_identity is None:
            raise HTTPException(status_code=400, detail="no stremio in this test")
        return stremio_identity

    monkeypatch.setattr(AuthService, "get_stremio_user_data", fake_stremio)

    async def fake_trakt_user(access_token):
        return {"username": "bob", "ids": {"slug": "trakt-bob"}}

    monkeypatch.setattr("app.services.auth.trakt_service.get_user_info", fake_trakt_user)

    async def fake_simkl_settings(access_token, client_id):
        return {"user": {"name": "bob"}, "account": {"id": 9876}}

    monkeypatch.setattr("app.services.auth.simkl_service.get_user_settings", fake_simkl_settings)

    return fake


def seed_account(fake: FakeRedis, token: str, last_updated: str, identities: dict[str, str] | None = None):
    blob = {
        "email": "someone@example.com",
        "settings": {"watch_history_source": "stremio", "catalogs": []},
        "last_updated": last_updated,
    }
    if identities:
        blob["identities"] = identities
        for provider, pid in identities.items():
            fake.data[f"watchly:identity:{provider}:{pid}"] = token
    fake.data[f"watchly:token:{token}"] = json.dumps(blob)


def test_trakt_only_account_minted_and_reused(monkeypatch):
    fake = setup_fakes(monkeypatch)
    service = AuthService()
    payload = TokenRequest(trakt_access_token="t-abc", watch_history_source="trakt")

    response, auth_key, _ = asyncio.run(service.create_user_token(payload))

    assert auth_key is None
    token = response.token
    assert token and token != "trakt-bob"
    assert fake.data["watchly:identity:trakt:trakt-bob"] == token

    # Re-configuring with the same Trakt account resolves to the same token
    response2, _, _ = asyncio.run(service.create_user_token(payload))
    assert response2.token == token


def test_at_least_one_account_required(monkeypatch):
    setup_fakes(monkeypatch)
    service = AuthService()

    with pytest.raises(HTTPException) as exc:
        asyncio.run(service.create_user_token(TokenRequest(watch_history_source="stremio")))
    assert exc.value.status_code == 400


def test_source_must_match_a_connected_provider(monkeypatch):
    setup_fakes(monkeypatch)
    service = AuthService()
    payload = TokenRequest(trakt_access_token="t-abc", watch_history_source="stremio")

    with pytest.raises(HTTPException) as exc:
        asyncio.run(service.create_user_token(payload))
    assert exc.value.status_code == 400


def test_legacy_stremio_account_keeps_its_token(monkeypatch):
    fake = setup_fakes(monkeypatch, stremio_identity=("user123", "user@example.com", "authkey-1"))
    # Pre-identity-index account: token IS the Stremio user id, no index entry.
    seed_account(fake, "user123", "2024-01-01T00:00:00+00:00")
    service = AuthService()
    payload = TokenRequest(authKey="some-key", watch_history_source="stremio")

    response, auth_key, _ = asyncio.run(service.create_user_token(payload))

    assert response.token == "user123"
    assert auth_key == "authkey-1"
    # Identity index is backfilled for the legacy account
    assert fake.data["watchly:identity:stremio:user123"] == "user123"


def test_identities_spanning_two_accounts_merge_into_oldest(monkeypatch):
    fake = setup_fakes(monkeypatch, stremio_identity=("user123", "user@example.com", "authkey-1"))
    seed_account(fake, "tok_trakt_first", "2023-05-01T00:00:00+00:00", identities={"trakt": "trakt-bob"})
    seed_account(fake, "user123", "2024-01-01T00:00:00+00:00")
    service = AuthService()
    payload = TokenRequest(authKey="some-key", trakt_access_token="t-abc", watch_history_source="trakt")

    response, _, _ = asyncio.run(service.create_user_token(payload))

    # Older (Trakt-first) account survives; both identities now point at it
    assert response.token == "tok_trakt_first"
    assert fake.data["watchly:identity:trakt:trakt-bob"] == "tok_trakt_first"
    assert fake.data["watchly:identity:stremio:user123"] == "tok_trakt_first"

    # Absorbed account is gone but its manifest token still resolves via alias
    assert "watchly:token:user123" not in fake.data
    assert asyncio.run(token_store.resolve_alias("user123")) == "tok_trakt_first"

    stored = json.loads(fake.data["watchly:token:tok_trakt_first"])
    assert stored["identities"] == {"trakt": "trakt-bob", "stremio": "user123"}


def test_relinking_keeps_identities_from_previous_configurations(monkeypatch):
    fake = setup_fakes(monkeypatch)
    service = AuthService()

    # First configure with Trakt + Simkl
    both = TokenRequest(trakt_access_token="t-abc", simkl_access_token="s-abc", watch_history_source="trakt")
    response, _, _ = asyncio.run(service.create_user_token(both))

    # Later submit with Trakt only — the Simkl identity link must survive
    trakt_only = TokenRequest(trakt_access_token="t-abc", watch_history_source="trakt")
    response2, _, _ = asyncio.run(service.create_user_token(trakt_only))

    assert response2.token == response.token
    assert fake.data["watchly:identity:simkl:9876"] == response.token
