import asyncio
import json

from app.services.token_store import TokenStore


def test_migrate_poster_rating_preserves_migrated_api_key(monkeypatch):
    store = TokenStore()
    writes: list[dict] = []

    async def fake_set(key: str, value: str, ttl=None):
        writes.append({"key": key, "value": value, "ttl": ttl})
        return True

    monkeypatch.setattr("app.services.token_store.redis_service.set", fake_set)

    payload = {
        "settings": {
            "rpdb_key": "plain-api-key",
        }
    }

    updated = asyncio.run(store._migrate_poster_rating_format_raw("user123", "watchly:token:user123", payload))

    assert updated is not None
    assert "rpdb_key" not in updated["settings"]
    assert updated["settings"]["poster_rating"]["provider"] == "rpdb"
    assert updated["settings"]["poster_rating"]["api_key"] is not None
    assert updated["settings"]["poster_rating"]["api_key"] != "plain-api-key"
    assert writes

    stored_payload = json.loads(writes[0]["value"])
    assert stored_payload["settings"]["poster_rating"]["api_key"] is not None


def test_token_request_defaults_match_user_settings_defaults():
    from app.api.models.tokens import TokenRequest
    from app.core.settings import UserSettings, get_default_year_max

    token_request = TokenRequest()
    user_settings = UserSettings(catalogs=[])

    assert token_request.year_min == user_settings.year_min == 1970
    assert token_request.year_max == user_settings.year_max == get_default_year_max()
