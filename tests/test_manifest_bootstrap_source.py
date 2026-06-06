import asyncio

import app.services.manifest as manifest_mod
from app.core.settings import get_default_settings
from app.models.library import LibraryCollection


def test_cache_library_and_profiles_uses_configured_source(monkeypatch):
    """#144: the bootstrap cache must use the user's configured watch_history_source,
    not always Stremio. Tagging the bootstrap library as 'stremio' for a Trakt user
    made load_user_context see a source mismatch and re-fetch the whole external
    history on every manifest request."""
    captured = {}

    async def fake_fetch_library_for_source(source, user_settings, token, bundle, auth_key):
        captured["fetch_source"] = source
        return LibraryCollection(source=source)

    async def fake_set_library_items(token, library_items):
        captured["cached_source"] = library_items.source

    class FakeProfileService:
        def __init__(self, *args, **kwargs):
            pass

        async def build_and_cache_profile(self, *args, **kwargs):
            return None, set(), set()

    monkeypatch.setattr(manifest_mod, "fetch_library_for_source", fake_fetch_library_for_source)
    monkeypatch.setattr(manifest_mod.user_cache, "set_library_items", fake_set_library_items)
    monkeypatch.setattr(manifest_mod, "ProfileService", FakeProfileService)

    user_settings = get_default_settings().model_copy(update={"watch_history_source": "trakt"})

    asyncio.run(
        manifest_mod.manifest_service.cache_library_and_profiles(
            bundle=object(), auth_key="ak", user_settings=user_settings, token="tok"
        )
    )

    assert captured["fetch_source"] == "trakt"
    assert captured["cached_source"] == "trakt"
