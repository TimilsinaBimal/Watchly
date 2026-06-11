import asyncio
import json

from app.core.settings import LLMConfig, UserSettings, resolve_llm_config
from app.models.profile import TasteProfile
from app.services.row_generator import RowGeneratorService
from app.services.token_store import TokenStore


def test_resolve_llm_config_prefers_llm_over_legacy():
    settings = UserSettings(
        catalogs=[],
        llm=LLMConfig(provider="anthropic", api_key="sk-ant-xxx"),
        gemini_api_key="old-gemini-key",
    )
    config = resolve_llm_config(settings)
    assert config.provider == "anthropic"
    assert config.api_key == "sk-ant-xxx"


def test_resolve_llm_config_wraps_legacy_gemini_key():
    settings = UserSettings(catalogs=[], gemini_api_key="old-gemini-key")
    config = resolve_llm_config(settings)
    assert config.provider == "gemini"
    assert config.api_key == "old-gemini-key"
    assert config.resolved_model() == "gemini-2.5-flash"


def test_resolve_llm_config_none_without_keys():
    assert resolve_llm_config(UserSettings(catalogs=[])) is None
    assert resolve_llm_config(None) is None


def test_token_store_encrypts_llm_api_key(monkeypatch):
    store = TokenStore()
    writes: list[str] = []

    async def fake_set(key, value, ttl=None):
        writes.append(value)
        return True

    monkeypatch.setattr("app.services.token_store.redis_service.set", fake_set)
    monkeypatch.setattr("app.services.token_store.settings.TOKEN_SALT", "unit-test-salt")

    payload = {"settings": {"llm": {"provider": "openai", "api_key": "sk-plain", "model": None}}}
    asyncio.run(store.store_user_data("tok1", payload))

    stored = json.loads(writes[0])
    encrypted = stored["settings"]["llm"]["api_key"]
    assert encrypted != "sk-plain"
    assert encrypted.startswith("gAAAAA")
    assert store.decrypt_token(encrypted) == "sk-plain"


def test_row_generator_uses_fallback_titles_without_llm_config(monkeypatch):
    async def fail_if_called(*args, **kwargs):
        raise AssertionError("LLM must not be called without a user key")

    monkeypatch.setattr("app.services.row_generator.llm_service.generate_title", fail_if_called)
    monkeypatch.setattr("app.services.row_generator.llm_service.generate_structured", fail_if_called)

    service = RowGeneratorService.__new__(RowGeneratorService)  # skip TMDB init

    async def no_keywords(self, ids):
        return {}

    monkeypatch.setattr(RowGeneratorService, "_resolve_keyword_names", no_keywords)

    profile = TasteProfile(genre_scores={28: 5.0, 53: 3.0, 18: 2.0})
    rows = asyncio.run(service.generate_rows(profile, "movie", llm_config=None))

    assert rows
    assert all(r.title and r.id.startswith("watchly.theme.") for r in rows)
