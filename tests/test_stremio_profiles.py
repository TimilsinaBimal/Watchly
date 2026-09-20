import asyncio

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.endpoints import stremio_profiles as profile_endpoints
from app.api.models.stremio_profiles import (
    StremioCredentialsRequest,
    StremioProfileAddonInstallRequest,
    StremioProfileAuthRequest,
)
from app.core.config import settings
from app.models.stremio_profile import StremioProfile
from app.services.stremio.addons import StremioAddonService
from app.services.stremio.auth import StremioAuthService


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    async def post(self, path, json):
        self.requests.append((path, json))
        return self.responses.pop(0)


def test_profiles_support_map_response_and_include_primary_profile():
    client = FakeClient(
        [
            {
                "result": {
                    "_id": "account-1",
                    "email": "owner@example.com",
                    "avatar": "owner.png",
                    "premiumPrefs": {
                        "userProfiles": {
                            "profile-2": {
                                "name": "Alice",
                                "avatar": 2,
                                "hasPin": True,
                                "canManageAddons": False,
                                "selected": True,
                            }
                        }
                    },
                }
            }
        ]
    )
    service = StremioAuthService(client)

    profiles = asyncio.run(service.get_profiles("master-key"))

    assert [profile.id for profile in profiles] == ["account-1", "profile-2"]
    assert profiles[0].is_master is True
    assert profiles[0].name == "owner@example.com"
    assert profiles[1].has_pin is True
    assert profiles[1].avatar == 2
    assert profiles[1].selected is True


ACCOUNT_WITH_SELECTED_SECONDARY = {
    "_id": "account-1",
    "email": "owner@example.com",
    "premiumPrefs": {
        "userProfiles": [
            {"_id": "account-1", "name": "Owner", "isMaster": True},
            {"_id": "profile-2", "name": "Alice", "selected": True},
        ]
    },
}


def test_root_key_keeps_the_bare_account_id_whatever_profile_is_selected():
    """Accounts indexed before profiles existed must keep resolving to the same
    identity when the Stremio app happens to be parked on a secondary profile."""
    service = StremioAuthService(FakeClient([{"result": ACCOUNT_WITH_SELECTED_SECONDARY}]))

    user_info = asyncio.run(service.get_user_info("root-key"))

    assert user_info == {
        "user_id": "account-1",
        "email": "owner@example.com",
        "profile_id": None,
        "profile_name": None,
    }


def test_profile_scoped_key_is_scoped_by_its_parent_id():
    scoped = {**ACCOUNT_WITH_SELECTED_SECONDARY, "_id": "profile-2", "parent_id": "account-1"}
    service = StremioAuthService(FakeClient([{"result": scoped}]))

    user_info = asyncio.run(service.get_user_info("profile-key"))

    assert user_info == {
        "user_id": "account-1:profile-2",
        "email": "owner@example.com",
        "profile_id": "profile-2",
        "profile_name": "Alice",
    }


def test_profiles_support_list_response_without_duplicating_primary_profile():
    client = FakeClient(
        [
            {
                "result": {
                    "_id": "account-1",
                    "email": "owner@example.com",
                    "premiumPrefs": {
                        "userProfiles": [
                            {"_id": "account-1", "name": "Owner", "canManageAddons": True},
                            {"profileId": "profile-2", "name": "Alice"},
                        ]
                    },
                }
            }
        ]
    )
    service = StremioAuthService(client)

    profiles = asyncio.run(service.get_profiles("master-key"))

    assert [profile.id for profile in profiles] == ["account-1", "profile-2"]
    assert profiles[0].is_master is True


def test_profile_without_pin_uses_authenticate_profile():
    client = FakeClient([{"result": {"authKey": "profile-key"}}])
    service = StremioAuthService(client)

    auth_key = asyncio.run(service.authenticate_profile("master-key", "profile-2"))

    assert auth_key == "profile-key"
    assert client.requests == [
        (
            "/api/premiumPrefs/authenticateProfile",
            {"type": "AuthenticateProfile", "authKey": "master-key", "profileId": "profile-2"},
        )
    ]


def test_empty_authentication_response_is_followed_by_profile_selection():
    client = FakeClient([{}, {"result": {"authKey": "profile-key"}}])
    service = StremioAuthService(client)

    auth_key = asyncio.run(service.authenticate_profile("master-key", "profile-2"))

    assert auth_key == "profile-key"
    assert client.requests == [
        (
            "/api/premiumPrefs/authenticateProfile",
            {"type": "AuthenticateProfile", "authKey": "master-key", "profileId": "profile-2"},
        ),
        (
            "/api/premiumPrefs/setProfile",
            {"type": "SetProfile", "authKey": "master-key", "profileId": "profile-2"},
        ),
    ]


def test_profile_with_pin_uses_authenticate_profile():
    client = FakeClient([{"result": {"user": {"authKey": "profile-key"}}}])
    service = StremioAuthService(client)

    auth_key = asyncio.run(service.authenticate_profile("master-key", "profile-2", "1234"))

    assert auth_key == "profile-key"
    assert client.requests == [
        (
            "/api/premiumPrefs/authenticateProfile",
            {
                "type": "AuthenticateProfile",
                "authKey": "master-key",
                "profileId": "profile-2",
                "pin": "1234",
            },
        )
    ]


def test_profile_authentication_rejects_missing_auth_key():
    client = FakeClient([{}, {"result": {}}])
    service = StremioAuthService(client)

    with pytest.raises(ValueError, match="did not return an auth key"):
        asyncio.run(service.authenticate_profile("master-key", "profile-2"))


def test_install_addon_replaces_only_the_matching_watchly_instance():
    existing_other_addon = {
        "manifest": {"id": "other.addon"},
        "transportUrl": "https://other.example/",
        "flags": {"official": False, "protected": False},
    }
    existing_watchly = {
        "manifest": {"id": settings.ADDON_ID, "name": "Old Watchly"},
        "transportUrl": f"{settings.HOST_NAME}/old/",
        "flags": {"official": False, "protected": False},
    }
    client = FakeClient(
        [
            {"result": {"addons": [existing_other_addon, existing_watchly]}},
            {"result": {"success": True}},
        ]
    )
    service = StremioAddonService(client)
    manifest = {"id": settings.ADDON_ID, "name": "Watchly - Alice"}
    manifest_url = f"{settings.HOST_NAME}/private-token/manifest.json"

    installed = asyncio.run(service.install_addon("profile-key", manifest_url, manifest))

    assert installed is True
    assert client.requests[1] == (
        "/api/addonCollectionSet",
        {
            "type": "AddonCollectionSet",
            "authKey": "profile-key",
            "addons": [
                existing_other_addon,
                {
                    "manifest": manifest,
                    "transportUrl": manifest_url,
                    "flags": {"official": False, "protected": False},
                },
            ],
        },
    )


def test_install_request_rejects_a_token_that_is_not_a_bare_token():
    StremioProfileAddonInstallRequest(authKey="profile-key", profile_id="profile-2", token="private-token_01")

    for token in ("../other", "a/b", "", "x" * 65):
        with pytest.raises(ValidationError):
            StremioProfileAddonInstallRequest(authKey="profile-key", profile_id="profile-2", token=token)


def test_authenticating_the_already_selected_profile_reuses_its_auth_key(monkeypatch):
    class FakeAuth:
        async def get_profiles(self, auth_key):
            return [StremioProfile(id="account-1", name="Téo", is_master=True, selected=True)]

        async def authenticate_profile(self, auth_key, profile_id, pin=None):
            raise AssertionError("Stremio should not be asked to switch to the already active profile")

        async def get_user_info(self, auth_key):
            return {
                "user_id": "account-1",
                "email": "owner@example.com",
                "profile_id": None,
                "profile_name": None,
            }

    class FakeBundle:
        def __init__(self):
            self.auth = FakeAuth()

        async def close(self):
            return None

    async def require_auth_key(bundle, credentials, token=None):
        return "master-key"

    monkeypatch.setattr(profile_endpoints, "StremioBundle", FakeBundle)
    monkeypatch.setattr(profile_endpoints.auth_service, "require_auth_key", require_auth_key)

    response = asyncio.run(
        profile_endpoints.authenticate_profile(StremioProfileAuthRequest(authKey="master-key", profile_id="account-1"))
    )

    assert response.authKey == "master-key"
    assert response.profile_id == "account-1"
    assert response.profile_name == "Téo"


def test_root_key_is_not_reused_for_a_secondary_profile_stremio_marks_selected(monkeypatch):
    class FakeAuth:
        async def get_profiles(self, auth_key):
            return [
                StremioProfile(id="account-1", name="Owner", is_master=True),
                StremioProfile(id="profile-2", name="Alice", selected=True),
            ]

        async def authenticate_profile(self, auth_key, profile_id, pin=None):
            assert (auth_key, profile_id) == ("root-key", "profile-2")
            return "alice-key"

        async def get_user_info(self, auth_key):
            return {
                "root-key": {"user_id": "account-1", "profile_id": None, "profile_name": None},
                "alice-key": {"user_id": "account-1:profile-2", "profile_id": "profile-2", "profile_name": "Alice"},
            }[auth_key]

    class FakeBundle:
        def __init__(self):
            self.auth = FakeAuth()

        async def close(self):
            return None

    async def require_auth_key(bundle, credentials, token=None):
        return "root-key"

    monkeypatch.setattr(profile_endpoints, "StremioBundle", FakeBundle)
    monkeypatch.setattr(profile_endpoints.auth_service, "require_auth_key", require_auth_key)

    response = asyncio.run(
        profile_endpoints.authenticate_profile(StremioProfileAuthRequest(authKey="root-key", profile_id="profile-2"))
    )

    assert response.authKey == "alice-key"
    assert response.profile_id == "profile-2"
    assert response.profile_name == "Alice"


def test_root_key_installs_the_primary_instance_but_not_a_secondary_one(monkeypatch):
    calls = []

    class FakeAuth:
        async def get_profiles(self, auth_key):
            return [
                StremioProfile(id="account-1", name="Owner", is_master=True),
                StremioProfile(id="profile-2", name="Alice"),
            ]

        async def get_user_info(self, auth_key):
            return {"user_id": "account-1", "profile_id": None, "profile_name": None}

    class FakeAddons:
        async def install_addon(self, auth_key, manifest_url, manifest):
            calls.append((auth_key, manifest_url, manifest))
            return True

    class FakeBundle:
        def __init__(self):
            self.auth = FakeAuth()
            self.addons = FakeAddons()

        async def close(self):
            return None

    async def get_manifest_for_token(token):
        return {"id": settings.ADDON_ID, "name": "Watchly"}

    monkeypatch.setattr(profile_endpoints, "StremioBundle", FakeBundle)
    monkeypatch.setattr(profile_endpoints.manifest_service, "get_manifest_for_token", get_manifest_for_token)

    response = asyncio.run(
        profile_endpoints.install_profile_addon(
            StremioProfileAddonInstallRequest(authKey="root-key", profile_id="account-1", token="primary-token")
        )
    )
    assert response.success is True
    assert calls == [
        ("root-key", f"{settings.HOST_NAME}/primary-token/manifest.json", {"id": settings.ADDON_ID, "name": "Watchly"})
    ]

    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(
            profile_endpoints.install_profile_addon(
                StremioProfileAddonInstallRequest(authKey="root-key", profile_id="profile-2", token="alice-token")
            )
        )
    assert excinfo.value.status_code == 400
    assert len(calls) == 1


def test_primary_profile_can_list_every_profile_instance(monkeypatch):
    class FakeAuth:
        async def get_profiles(self, auth_key):
            return [
                StremioProfile(id="account-1", name="Téo", is_master=True, selected=True),
                StremioProfile(id="profile-2", name="Alice"),
            ]

        async def get_user_info(self, auth_key):
            return {
                "user_id": "account-1",
                "profile_id": None,
                "profile_name": None,
            }

    class FakeBundle:
        def __init__(self):
            self.auth = FakeAuth()

        async def close(self):
            return None

    async def require_auth_key(bundle, credentials, token=None):
        return "master-key"

    async def get_token_for_identity(provider, identity_id):
        return {
            "account-1": "primary-token",
            "account-1:profile-2": "alice-token",
        }.get(identity_id)

    monkeypatch.setattr(profile_endpoints, "StremioBundle", FakeBundle)
    monkeypatch.setattr(profile_endpoints.auth_service, "require_auth_key", require_auth_key)
    monkeypatch.setattr(profile_endpoints.token_store, "get_token_for_identity", get_token_for_identity)

    response = asyncio.run(profile_endpoints.list_profile_instances(StremioCredentialsRequest(authKey="master-key")))

    assert [instance.model_dump() for instance in response.instances] == [
        {"profile_id": "account-1", "profile_name": "Téo", "token": "primary-token"},
        {"profile_id": "profile-2", "profile_name": "Alice", "token": "alice-token"},
    ]


def test_secondary_profile_can_only_list_its_own_instance(monkeypatch):
    class FakeAuth:
        async def get_profiles(self, auth_key):
            return [
                StremioProfile(id="account-1", name="Téo", is_master=True),
                StremioProfile(id="profile-2", name="Alice", selected=True),
            ]

        async def get_user_info(self, auth_key):
            return {
                "user_id": "account-1:profile-2",
                "profile_id": "profile-2",
                "profile_name": "Alice",
            }

    class FakeBundle:
        def __init__(self):
            self.auth = FakeAuth()

        async def close(self):
            return None

    async def require_auth_key(bundle, credentials, token=None):
        return "profile-key"

    async def get_token_for_identity(provider, identity_id):
        assert provider == "stremio"
        assert identity_id == "account-1:profile-2"
        return "alice-token"

    monkeypatch.setattr(profile_endpoints, "StremioBundle", FakeBundle)
    monkeypatch.setattr(profile_endpoints.auth_service, "require_auth_key", require_auth_key)
    monkeypatch.setattr(profile_endpoints.token_store, "get_token_for_identity", get_token_for_identity)

    response = asyncio.run(profile_endpoints.list_profile_instances(StremioCredentialsRequest(authKey="profile-key")))

    assert [instance.model_dump() for instance in response.instances] == [
        {"profile_id": "profile-2", "profile_name": "Alice", "token": "alice-token"}
    ]
