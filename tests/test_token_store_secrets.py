import asyncio
import json

import pytest

from app.core.security import _SECRET_NESTED_FIELDS, _SECRET_SETTINGS_FIELDS
from app.services.token_store import TokenStore


def _store(monkeypatch) -> tuple[TokenStore, list[str]]:
    store = TokenStore()
    writes: list[str] = []

    async def fake_set(key, value, ttl=None):
        writes.append(value)
        return True

    monkeypatch.setattr("app.services.token_store.redis_service.set", fake_set)
    monkeypatch.setattr("app.services.token_store.settings.TOKEN_SALT", "unit-test-salt")
    return store, writes


def _payload() -> dict:
    user_settings = {field: f"plain-{field}" for field in _SECRET_SETTINGS_FIELDS}
    for field in _SECRET_NESTED_FIELDS:
        user_settings[field] = {"api_key": f"plain-{field}"}
    return {"authKey": "plain-auth", "settings": user_settings}


def test_every_secret_field_is_encrypted_and_the_caller_dict_is_untouched(monkeypatch):
    store, writes = _store(monkeypatch)
    payload = _payload()

    asyncio.run(store.store_user_data("tok1", payload))

    assert payload == _payload()
    stored = json.loads(writes[0])["settings"]
    for field in _SECRET_SETTINGS_FIELDS:
        assert store.decrypt_token(stored[field]) == f"plain-{field}"
    for field in _SECRET_NESTED_FIELDS:
        assert store.decrypt_token(stored[field]["api_key"]) == f"plain-{field}"


def test_an_encryption_failure_raises_instead_of_storing_plaintext(monkeypatch):
    store, writes = _store(monkeypatch)

    def broken(value):
        raise ValueError("cipher unavailable")

    monkeypatch.setattr(store, "encrypt_token", broken)

    with pytest.raises(ValueError):
        asyncio.run(store.store_user_data("tok1", {"settings": {"tmdb_api_key": "plain"}}))
    assert writes == []


def test_already_encrypted_values_are_not_encrypted_twice(monkeypatch):
    store, writes = _store(monkeypatch)
    monkeypatch.setattr("app.services.token_store.settings.TOKEN_SALT", "unit-test-salt")
    encrypted = store.encrypt_token("plain")

    asyncio.run(store.store_user_data("tok1", {"settings": {"tmdb_api_key": encrypted}}))

    assert json.loads(writes[0])["settings"]["tmdb_api_key"] == encrypted
