import asyncio

import pytest

from app.core.settings import get_default_settings
from app.models.library import LibraryCollection, StremioLibraryItem
from app.services import catalog_updater as catalog_updater_module
from app.services import manifest as manifest_module
from app.services.catalog_updater import catalog_updater
from app.services.manifest import manifest_service
from app.services.token_store import token_store
from app.services.user_cache import user_cache

TOKEN = "tok_refresh"


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

    async def getex(self, key: str, ttl: int):
        return self.data.get(key)

    async def delete_by_pattern(self, pattern: str):
        return 0


def library_of(*imdb_ids: str, source: str) -> LibraryCollection:
    return LibraryCollection(
        watched=[
            StremioLibraryItem(_id=imdb_id, type="movie", name=imdb_id, temp=False, removed=False)
            for imdb_id in imdb_ids
        ],
        source=source,
    )


class Refresh:
    """What one refresh fetched, and what the profiles and the manifest were built from."""

    def __init__(self):
        self.fetched: list[tuple[str, str | None]] = []
        self.profiles: dict[str, list[str]] = {}
        self.manifest: list[list[str]] = []


@pytest.fixture
def refresh(monkeypatch):
    """Real token_store and auth_service over a fake Redis. Only Stremio, the library
    fetch, the TMDB-backed profile build and the manifest assembly are stubbed."""
    fake = FakeRedis()
    for name in ("get", "set", "delete", "getex", "delete_by_pattern"):
        monkeypatch.setattr(f"app.services.user_cache.redis_service.{name}", getattr(fake, name))
    monkeypatch.setattr("app.services.token_store.settings.TOKEN_SALT", "unit-test-salt")
    token_store._get_user_data_cached.cache_clear()
    seen = Refresh()

    async def fetch(source, user_settings, token, bundle, auth_key):
        seen.fetched.append((source, user_settings.tmdb_api_key))
        return library_of("tt0000001", "tt0000002", source=source)

    class RecordingProfileService:
        def __init__(self, *args, **kwargs):
            pass

        async def build_and_cache_profile(self, token, content_type, library_items, *args, **kwargs):
            seen.profiles[content_type] = sorted(i.id for i in library_items.all_items())
            return None, set(), set()

    async def rebuild_manifest(token, force_rebuild=False):
        library = await user_cache.get_library_items(token)
        seen.manifest.append(sorted(i.id for i in library.all_items()))
        return {"catalogs": []}

    monkeypatch.setattr(manifest_module, "fetch_library_for_source", fetch)
    monkeypatch.setattr(manifest_module, "ProfileService", RecordingProfileService)
    monkeypatch.setattr(manifest_service, "get_manifest_for_token", rebuild_manifest)
    return seen


def use_stremio(monkeypatch, stored_key_valid: bool):
    class Auth:
        async def get_user_info(self, auth_key):
            if not stored_key_valid:
                raise ValueError("Stremio API Error: Session not found")
            return {"_id": "stremio-user"}

        async def login(self, email, password):
            return "new-auth-key"

    class Addons:
        async def is_addon_installed(self, auth_key):
            return True

        async def update_catalogs(self, auth_key, catalogs):
            return True

    class Bundle:
        def __init__(self):
            self.auth = Auth()
            self.addons = Addons()

        async def close(self):
            pass

    monkeypatch.setattr(catalog_updater_module, "StremioBundle", Bundle)


async def stored_credentials(**settings) -> dict:
    """Store a user through the real token_store and return the process-cached dict the
    catalog endpoint hands to the updater."""
    user_settings = get_default_settings().model_copy(update=settings)
    payload = {"authKey": "auth-key", "email": "me@example.com", "password": "hunter2"}
    await token_store.store_user_data(TOKEN, {**payload, "settings": user_settings.model_dump()})
    return await token_store.get_user_data(TOKEN)


def test_scheduled_refresh_rebuilds_from_a_freshly_fetched_library(refresh, monkeypatch):
    """The scheduled refresh is the only rebuild an active user gets, and reading the
    cached library renews its TTL. If the refresh reuses that cache, nothing watched
    after the first fetch ever reaches the profile or the rows."""
    use_stremio(monkeypatch, stored_key_valid=True)
    credentials = asyncio.run(stored_credentials())
    asyncio.run(user_cache.set_library_items(TOKEN, library_of("tt0000001", source="stremio")))

    assert asyncio.run(catalog_updater.refresh_catalogs_for_credentials(TOKEN, credentials, update_timestamp=False))

    assert [source for source, _ in refresh.fetched] == ["stremio"]
    assert refresh.manifest == [["tt0000001", "tt0000002"]]
    assert refresh.profiles == {"movie": ["tt0000001", "tt0000002"], "series": ["tt0000001", "tt0000002"]}


def test_refresh_reads_settings_before_a_stremio_relogin_can_encrypt_them(refresh, monkeypatch):
    """A rejected authKey makes resolve_auth_key_with_bundle log in again and store the
    shared credentials dict, and store_user_data encrypts its nested settings in place.
    Settings read after that step would send ciphertext to Trakt, Simkl and TMDB."""
    use_stremio(monkeypatch, stored_key_valid=False)

    async def refresh_from_the_catalog_endpoint():
        # One event loop, as in the app: alru_cache clears itself when the loop
        # changes, and only within one loop is the endpoint's dict the one the
        # re-login stores.
        credentials = await stored_credentials(tmdb_api_key="plain-tmdb-key")
        await catalog_updater.refresh_catalogs_for_credentials(TOKEN, credentials, update_timestamp=False)

    asyncio.run(refresh_from_the_catalog_endpoint())

    assert refresh.fetched == [("stremio", "plain-tmdb-key")]


@pytest.mark.parametrize("source", ["trakt", "simkl"])
def test_refresh_leaves_a_trakt_or_simkl_library_as_it_is(refresh, monkeypatch, source):
    """Trakt and Simkl report an outage or a rejected token as an empty history, so a
    scheduled refetch would cache that over the user's library. They keep the library
    from setup until their fetches can tell a failure from an empty history."""
    use_stremio(monkeypatch, stored_key_valid=True)
    credentials = asyncio.run(stored_credentials(watch_history_source=source))
    asyncio.run(user_cache.set_library_items(TOKEN, library_of("tt0000001", source=source)))

    assert asyncio.run(catalog_updater.refresh_catalogs_for_credentials(TOKEN, credentials, update_timestamp=False))

    assert refresh.fetched == []
    assert refresh.manifest == [["tt0000001"]]
