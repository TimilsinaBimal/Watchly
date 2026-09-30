import asyncio
import copy

import pytest

from app.core.settings import get_default_settings
from app.services import catalog_updater as catalog_updater_module
from app.services.catalog_updater import catalog_updater
from app.services.manifest import manifest_service
from app.services.token_store import token_store

TOKEN = "tok_stamp"


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

    async def delete_by_pattern(self, pattern: str):
        return 0


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
def stored_user(monkeypatch):
    """A real, encrypted token_store record, and the process-cached credentials dict
    the catalog endpoint hands to the updater. The rebuild itself is stubbed: these
    tests are about what the updater writes back afterwards."""
    fake = FakeRedis()
    for name in ("get", "set", "delete", "delete_by_pattern"):
        monkeypatch.setattr(f"app.services.token_store.redis_service.{name}", getattr(fake, name))
    monkeypatch.setattr("app.services.token_store.settings.TOKEN_SALT", "unit-test-salt")
    token_store._get_user_data_cached.cache_clear()

    async def resolve_auth_key(bundle, credentials, token):
        return "auth-key"

    async def no_library_refresh(bundle, auth_key, user_settings, token):
        return None

    monkeypatch.setattr(catalog_updater_module, "StremioBundle", OfflineBundle)
    monkeypatch.setattr(catalog_updater_module.auth_service, "resolve_auth_key_with_bundle", resolve_auth_key)
    monkeypatch.setattr(manifest_service, "cache_library_and_profiles", no_library_refresh)

    user_settings = get_default_settings().model_copy(
        update={"trakt_access_token": "access-token", "trakt_refresh_token": "original"}
    )
    asyncio.run(token_store.store_user_data(TOKEN, {"authKey": "auth-key", "settings": user_settings.model_dump()}))
    return asyncio.run(token_store.get_user_data(TOKEN))


def read_back() -> dict | None:
    token_store._get_user_data_cached.cache_clear()
    return asyncio.run(token_store.get_user_data(TOKEN))


def test_refresh_stamps_the_stored_credentials_not_its_snapshot(stored_user, monkeypatch):
    """A Trakt token rotation or a settings save can replace the stored credentials while
    a refresh runs. Writing the refresh's starting snapshot back afterwards restores the
    old values, and for Trakt that is a refresh token the rotation already spent."""
    shared = stored_user
    held_by_other_requests = []

    async def rebuild_while_trakt_rotates(token, force_rebuild=False):
        rotated = copy.deepcopy(await token_store.get_user_data(token))
        rotated["settings"]["trakt_refresh_token"] = "rotated"
        await token_store.update_user_data(token, rotated)
        held_by_other_requests.append(await token_store.get_user_data(token))
        return {"catalogs": []}

    monkeypatch.setattr(manifest_service, "get_manifest_for_token", rebuild_while_trakt_rotates)

    assert asyncio.run(catalog_updater.refresh_catalogs_for_credentials(TOKEN, shared))

    stored = read_back()
    assert stored["settings"]["trakt_refresh_token"] == "rotated"
    assert "last_updated" in stored
    # Process-cached credentials are read-only (CLAUDE.md): store_user_data encrypts the
    # nested settings of whatever dict it is handed, in place.
    for cached in (shared, held_by_other_requests[0]):
        assert "last_updated" not in cached
        assert cached["settings"]["trakt_access_token"] == "access-token"


def test_refresh_does_not_recreate_a_token_deleted_while_it_ran(stored_user, monkeypatch):
    async def rebuild_while_user_deletes_account(token, force_rebuild=False):
        await token_store.delete_token(token)
        return {"catalogs": []}

    monkeypatch.setattr(manifest_service, "get_manifest_for_token", rebuild_while_user_deletes_account)

    asyncio.run(catalog_updater.refresh_catalogs_for_credentials(TOKEN, stored_user))

    assert read_back() is None
