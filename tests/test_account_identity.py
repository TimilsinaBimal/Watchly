import asyncio
import json

import httpx
import pytest
from fastapi import HTTPException

from app.api.models.tokens import TokenRequest
from app.core.security import STORED_SECRET_SENTINEL
from app.core.settings import LLMConfig
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


def test_recall_account_via_trakt(monkeypatch):
    fake = setup_fakes(monkeypatch)
    seed_account(fake, "tok_xyz", "2024-01-01T00:00:00+00:00", identities={"trakt": "trakt-bob"})
    service = AuthService()

    result = asyncio.run(service.get_identity_with_settings(TokenRequest(trakt_access_token="t-abc")))

    assert result["exists"] is True
    assert result["token"] == "tok_xyz"
    assert result["user_id"] == "trakt-bob"
    assert result["settings"]["watch_history_source"] == "stremio"


def test_resubmit_without_stremio_keeps_stremio_credentials(monkeypatch):
    setup_fakes(monkeypatch, stremio_identity=("user123", "user@example.com", "authkey-1"))
    service = AuthService()

    both = TokenRequest(authKey="some-key", trakt_access_token="t-abc", watch_history_source="stremio")
    response, _, _ = asyncio.run(service.create_user_token(both))

    trakt_only = TokenRequest(trakt_access_token="t-abc", watch_history_source="trakt")
    response2, auth_key2, _ = asyncio.run(service.create_user_token(trakt_only))

    assert response2.token == response.token
    assert auth_key2 is None
    stored = asyncio.run(token_store.get_user_data(response.token))
    assert stored["authKey"] == "authkey-1"
    assert stored["user_id"] == "user123"
    assert stored["email"] == "user@example.com"


def only_valid_trakt_token(monkeypatch, valid_token: str | None):
    """Make Trakt reject every access token except `valid_token`."""

    async def fake_trakt_user(access_token):
        if access_token != valid_token:
            raise httpx.HTTPStatusError("401", request=None, response=httpx.Response(401))
        return {"username": "bob", "ids": {"slug": "trakt-bob"}}

    monkeypatch.setattr("app.services.auth.trakt_service.get_user_info", fake_trakt_user)


def test_expired_trakt_token_is_refreshed_and_stored(monkeypatch):
    setup_fakes(monkeypatch)
    only_valid_trakt_token(monkeypatch, "t-new")
    refresh_calls = []

    async def fake_refresh(refresh_token, redirect_uri):
        refresh_calls.append(refresh_token)
        return {"access_token": "t-new", "refresh_token": "r-new", "expires_in": 7776000, "created_at": 1000}

    monkeypatch.setattr("app.services.auth.trakt_service.refresh_token", fake_refresh)

    service = AuthService()
    payload = TokenRequest(
        trakt_access_token="t-expired",
        trakt_refresh_token="r-old",
        watch_history_source="trakt",
    )

    response, _, user_settings = asyncio.run(service.create_user_token(payload))

    assert refresh_calls == ["r-old"]
    assert user_settings.trakt_access_token == "t-new"
    stored = asyncio.run(token_store.get_user_data(response.token))
    assert stored["settings"]["trakt_access_token"] == "t-new"
    assert stored["settings"]["trakt_refresh_token"] == "r-new"
    # Trakt rotates refresh tokens, so the client has to be told the new pair
    assert response.refreshedTrakt.access_token == "t-new"
    assert response.refreshedTrakt.refresh_token == "r-new"
    assert response.refreshedTrakt.expires_at == 1000 + 7776000


def test_unverifiable_trakt_does_not_block_a_stremio_save(monkeypatch):
    setup_fakes(monkeypatch, stremio_identity=("user123", "user@example.com", "authkey-1"))
    only_valid_trakt_token(monkeypatch, None)

    async def fail_if_called(refresh_token, redirect_uri):
        raise AssertionError("must not refresh without a refresh token")

    monkeypatch.setattr("app.services.auth.trakt_service.refresh_token", fail_if_called)

    service = AuthService()
    payload = TokenRequest(authKey="some-key", trakt_access_token="t-dead", watch_history_source="stremio")

    response, auth_key, _ = asyncio.run(service.create_user_token(payload))

    assert auth_key == "authkey-1"
    stored = asyncio.run(token_store.get_user_data(response.token))
    assert stored["identities"] == {"stremio": "user123"}
    # The dead token is still stored; the profile pipeline refreshes or clears it later.
    assert stored["settings"]["trakt_access_token"] == "t-dead"


def test_unverifiable_source_provider_is_rejected(monkeypatch):
    setup_fakes(monkeypatch)
    only_valid_trakt_token(monkeypatch, None)
    service = AuthService()
    payload = TokenRequest(trakt_access_token="t-dead", watch_history_source="trakt")

    with pytest.raises(HTTPException) as exc:
        asyncio.run(service.create_user_token(payload))
    assert exc.value.status_code == 400


def test_identity_lookup_never_spends_the_refresh_token(monkeypatch):
    """Refreshing rotates the stored pair, so a read-only lookup must not do it."""
    setup_fakes(monkeypatch)
    only_valid_trakt_token(monkeypatch, None)

    async def fail_if_called(refresh_token, redirect_uri):
        raise AssertionError("get_identity_with_settings must not refresh")

    monkeypatch.setattr("app.services.auth.trakt_service.refresh_token", fail_if_called)

    service = AuthService()
    payload = TokenRequest(trakt_access_token="t-expired", trakt_refresh_token="r-old")

    with pytest.raises(HTTPException) as exc:
        asyncio.run(service.get_identity_with_settings(payload))
    assert exc.value.status_code == 400


def test_identity_lookup_masks_stored_secrets(monkeypatch):
    fake = setup_fakes(monkeypatch)
    service = AuthService()
    asyncio.run(
        service.create_user_token(
            TokenRequest(
                trakt_access_token="t-abc",
                trakt_refresh_token="r-abc",
                watch_history_source="trakt",
                tmdb_api_key="tmdb-secret",
                llm=LLMConfig(provider="anthropic", api_key="sk-ant-secret"),
            )
        )
    )

    result = asyncio.run(service.get_identity_with_settings(TokenRequest(trakt_access_token="t-abc")))

    settings = result["settings"]
    for field in ("tmdb_api_key", "trakt_access_token", "trakt_refresh_token"):
        assert settings[field] == STORED_SECRET_SENTINEL
    assert settings["llm"]["api_key"] == STORED_SECRET_SENTINEL
    # Non-secret settings still come through so the page can restore them
    assert settings["llm"]["provider"] == "anthropic"
    assert settings["watch_history_source"] == "trakt"
    assert STORED_SECRET_SENTINEL not in json.dumps(fake.data)


def test_resubmitting_masked_secrets_keeps_the_stored_values(monkeypatch):
    setup_fakes(monkeypatch)
    service = AuthService()
    first = TokenRequest(
        trakt_access_token="t-abc",
        trakt_refresh_token="r-abc",
        watch_history_source="trakt",
        tmdb_api_key="tmdb-secret",
        llm=LLMConfig(provider="anthropic", api_key="sk-ant-secret"),
    )
    response, _, _ = asyncio.run(service.create_user_token(first))

    # What the configure page sends back after loading masked settings
    masked = TokenRequest(
        trakt_access_token=STORED_SECRET_SENTINEL,
        trakt_refresh_token=STORED_SECRET_SENTINEL,
        watch_history_source="trakt",
        tmdb_api_key=STORED_SECRET_SENTINEL,
        llm=LLMConfig(provider="anthropic", api_key=STORED_SECRET_SENTINEL),
        language="de-DE",
    )
    response2, _, user_settings = asyncio.run(service.create_user_token(masked))

    assert response2.token == response.token
    assert user_settings.tmdb_api_key == "tmdb-secret"
    assert user_settings.trakt_access_token == "t-abc"
    assert user_settings.trakt_refresh_token == "r-abc"
    assert user_settings.llm.api_key == "sk-ant-secret"
    assert user_settings.language == "de-DE"


def test_masked_key_is_not_carried_across_providers(monkeypatch):
    setup_fakes(monkeypatch)
    service = AuthService()
    asyncio.run(
        service.create_user_token(
            TokenRequest(
                trakt_access_token="t-abc",
                watch_history_source="trakt",
                llm=LLMConfig(provider="anthropic", api_key="sk-ant-secret"),
            )
        )
    )

    switched = TokenRequest(
        trakt_access_token="t-abc",
        watch_history_source="trakt",
        llm=LLMConfig(provider="openai", api_key=STORED_SECRET_SENTINEL),
    )
    _, _, user_settings = asyncio.run(service.create_user_token(switched))

    assert user_settings.llm is None


def test_masked_legacy_gemini_key_migrates_into_llm(monkeypatch):
    """The page shows a legacy gemini_api_key in the LLM fields, so it comes back masked."""
    setup_fakes(monkeypatch)
    service = AuthService()
    asyncio.run(
        service.create_user_token(
            TokenRequest(trakt_access_token="t-abc", watch_history_source="trakt", gemini_api_key="legacy-gemini")
        )
    )

    masked = TokenRequest(
        trakt_access_token="t-abc",
        watch_history_source="trakt",
        llm=LLMConfig(provider="gemini", api_key=STORED_SECRET_SENTINEL),
    )
    _, _, user_settings = asyncio.run(service.create_user_token(masked))

    assert user_settings.llm.api_key == "legacy-gemini"


def test_emptied_secret_field_still_clears_the_stored_value(monkeypatch):
    setup_fakes(monkeypatch)
    service = AuthService()
    asyncio.run(
        service.create_user_token(
            TokenRequest(trakt_access_token="t-abc", watch_history_source="trakt", tmdb_api_key="tmdb-secret")
        )
    )

    cleared = TokenRequest(trakt_access_token="t-abc", watch_history_source="trakt", tmdb_api_key="")
    _, _, user_settings = asyncio.run(service.create_user_token(cleared))

    assert not user_settings.tmdb_api_key


def test_masked_trakt_token_still_saves_with_trakt_as_source(monkeypatch):
    """The page can't re-verify a masked token, but the link is already on record."""
    setup_fakes(monkeypatch, stremio_identity=("user123", "user@example.com", "authkey-1"))
    service = AuthService()
    asyncio.run(
        service.create_user_token(
            TokenRequest(authKey="some-key", trakt_access_token="t-abc", watch_history_source="trakt")
        )
    )
    only_valid_trakt_token(monkeypatch, None)

    resubmit = TokenRequest(
        authKey="some-key",
        trakt_access_token=STORED_SECRET_SENTINEL,
        watch_history_source="trakt",
    )
    _, _, user_settings = asyncio.run(service.create_user_token(resubmit))

    assert user_settings.trakt_access_token == "t-abc"
    assert user_settings.watch_history_source == "trakt"


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
