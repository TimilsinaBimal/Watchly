import asyncio
import fnmatch

import pytest

from app.core.constants import DISCOVER_ONLY_EXTRA
from app.core.settings import get_default_settings
from app.models.library import LibraryCollection, StremioLibraryItem
from app.services import catalog_updater as catalog_updater_module
from app.services import manifest as manifest_module
from app.services.catalog_updater import catalog_updater
from app.services.manifest import manifest_service
from app.services.recommendation import catalog_service as cs_module
from app.services.recommendation.catalog_service import catalog_service
from app.services.token_store import token_store
from app.services.user_cache import user_cache

TOKEN = "tok_rows"
ROWS = [
    {"type": "movie", "id": "watchly.rec"},
    {"type": "series", "id": "watchly.theme.1"},
    {"type": "movie", "id": "watchly.theme.2", "extra": DISCOVER_ONLY_EXTRA},
]


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

    async def getex(self, key: str, ttl: int):
        return self.data.get(key)

    async def delete_by_pattern(self, pattern: str):
        doomed = [key for key in self.data if fnmatch.fnmatchcase(key, pattern)]
        for key in doomed:
            del self.data[key]
        return len(doomed)


class OfflineAddons:
    async def is_addon_installed(self, auth_key):
        return True

    async def update_catalogs(self, auth_key, catalogs):
        return True


class OfflineBundle:
    def __init__(self):
        self.addons = OfflineAddons()

    async def close(self):
        pass


@pytest.fixture
def due_refresh(monkeypatch):
    """A stored user with a refresh due, and yesterday's rows cached. Stremio, the
    library fetch, the profile build, the manifest assembly and each row's
    recommendations are stubbed; the cache, get_catalog and the updater are real."""
    fake = FakeRedis()
    for name in ("get", "set", "set_nx", "delete", "exists", "getex", "delete_by_pattern"):
        monkeypatch.setattr(f"app.services.user_cache.redis_service.{name}", getattr(fake, name))
    monkeypatch.setattr("app.services.token_store.settings.TOKEN_SALT", "unit-test-salt")
    token_store._get_user_data_cached.cache_clear()

    async def resolve_auth_key(bundle, credentials, token):
        return "auth-key"

    async def fetch(source, user_settings, token, bundle, auth_key):
        return LibraryCollection(
            watched=[StremioLibraryItem(_id="tt0000002", type="movie", name="New", temp=False, removed=False)],
            source=source,
        )

    class NoProfiles:
        def __init__(self, *args, **kwargs):
            pass

        async def build_and_cache_profile(self, *args, **kwargs):
            return None, set(), set()

    async def rebuild_manifest(token, force_rebuild=False):
        return {"catalogs": ROWS}

    async def load_context(token, require_auth=True):
        class Ctx:
            async def close(self):
                pass

        ctx = Ctx()
        ctx.token = token
        return ctx

    async def build_row(ctx, content_type, catalog_id, headers):
        data = {"metas": [{"id": f"new:{catalog_id}", "type": content_type, "name": "New"}]}
        # What the real _build_catalog does with a non-empty result.
        await user_cache.set_catalog(ctx.token, content_type, catalog_id, data, cs_module.settings.CATALOG_STALE_TTL)
        return data, headers

    monkeypatch.setattr(catalog_updater_module, "StremioBundle", OfflineBundle)
    monkeypatch.setattr(catalog_updater_module.auth_service, "resolve_auth_key_with_bundle", resolve_auth_key)
    monkeypatch.setattr(manifest_module, "fetch_library_for_source", fetch)
    monkeypatch.setattr(manifest_module, "ProfileService", NoProfiles)
    monkeypatch.setattr(manifest_service, "get_manifest_for_token", rebuild_manifest)
    monkeypatch.setattr(cs_module, "load_user_context", load_context)
    monkeypatch.setattr(catalog_service, "_build_catalog", build_row)

    async def setup():
        settings = get_default_settings().model_dump()
        await token_store.store_user_data(TOKEN, {"authKey": "auth-key", "settings": settings})
        for row in ROWS:
            old = {"metas": [{"id": f"old:{row['id']}", "type": row["type"], "name": "Old"}]}
            await user_cache.set_catalog(TOKEN, row["type"], row["id"], old, cs_module.settings.CATALOG_STALE_TTL)

    asyncio.run(setup())


def cached_row(content_type: str, catalog_id: str) -> str | None:
    cached = asyncio.run(user_cache.get_catalog(TOKEN, content_type, catalog_id))
    return cached[0]["metas"][0]["id"] if cached else None


def test_refresh_leaves_every_row_rebuilt_and_cached(due_refresh):
    """Writing the new library drops every cached row. Unless the refresh builds them,
    the next home screen after each daily refresh waits on every one."""

    async def run_the_scheduled_refresh():
        credentials = await token_store.get_user_data(TOKEN)
        await catalog_updater.trigger_update(TOKEN, credentials)
        await asyncio.gather(*list(catalog_updater._running.values()))

    asyncio.run(run_the_scheduled_refresh())

    assert cached_row("movie", "watchly.rec") == "new:watchly.rec"
    assert cached_row("series", "watchly.theme.1") == "new:watchly.theme.1"
    # Stremio's home board skips a row with a required extra; it's built when opened in Discover.
    assert cached_row("movie", "watchly.theme.2") is None


def test_a_failed_refresh_leaves_rows_to_their_own_requests(due_refresh, monkeypatch):
    """A failed push leaves last_updated unstamped, so the refresh runs again on the next
    request. Rebuilding every row each time would repeat the whole job per request."""

    async def push_fails(self, auth_key, catalogs):
        return False

    monkeypatch.setattr(OfflineAddons, "update_catalogs", push_fails)

    async def run_the_scheduled_refresh():
        credentials = await token_store.get_user_data(TOKEN)
        await catalog_updater.trigger_update(TOKEN, credentials)
        await asyncio.gather(*list(catalog_updater._running.values()))

    asyncio.run(run_the_scheduled_refresh())

    assert cached_row("movie", "watchly.rec") is None


def test_an_account_removed_during_the_refresh_does_not_fail_it(due_refresh, monkeypatch):
    """A row that fails to build is served as an empty one, so what reaches the rebuild
    loop is the account itself. Letting it escape would turn a finished refresh into a
    failed one, and a failure pushes an error status to the user's addon."""

    async def rebuild_while_user_deletes_account(token, force_rebuild=False):
        await token_store.delete_token(token)
        return {"catalogs": ROWS}

    monkeypatch.setattr(manifest_service, "get_manifest_for_token", rebuild_while_user_deletes_account)

    async def run_the_scheduled_refresh():
        credentials = await token_store.get_user_data(TOKEN)
        return await catalog_updater.refresh_catalogs_for_credentials(TOKEN, credentials)

    assert asyncio.run(run_the_scheduled_refresh())
