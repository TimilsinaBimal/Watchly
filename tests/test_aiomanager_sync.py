import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.models.tokens import TokenRequest
from app.core.app import app
from app.core.security import _SECRET_SETTINGS_FIELDS, STORED_SECRET_SENTINEL
from app.core.settings import get_default_settings
from app.services.aiomanager import AIOManagerError, AIOManagerService
from app.services.auth import auth_service

client = TestClient(app)

TOKEN = "tok-aiomanager"
INSTANCE = "https://aiomanager.example.com"
REINSTALL_URL = f"{INSTANCE}/hydra/reinstall"
ADDONS_URL = f"{INSTANCE}/hydra/addons"
STATUS_URL = f"{INSTANCE}/hydra/status"


class FakeHydraClient:
    """Stands in for BaseClient: records the calls and answers whatever the handler returns.

    Handlers raise the real httpx errors, so the service's translation is exercised
    rather than bypassed.
    """

    def __init__(self, handler):
        self.handler = handler
        self.calls: list[tuple[str, str]] = []

    async def get(self, url, **kwargs):
        self.calls.append(("GET", url))
        return self.handler("GET", url)

    async def post(self, url, **kwargs):
        self.calls.append(("POST", url))
        return self.handler("POST", url)


def _http_error(status, *, url=REINSTALL_URL, body=None, method="POST"):
    request = httpx.Request(method, url)
    return httpx.HTTPStatusError(
        f"HTTP {status}", request=request, response=httpx.Response(status, json=body or {}, request=request)
    )


def _service(monkeypatch, handler) -> AIOManagerService:
    service = AIOManagerService()
    monkeypatch.setattr(service, "client", FakeHydraClient(handler))
    return service


def _accounts(monkeypatch, credentials):
    """Serve one account out of the token store without Redis."""

    async def fake_resolve_alias(token):
        return token

    async def fake_get_user_data(token):
        return credentials if token == TOKEN else None

    monkeypatch.setattr("app.api.endpoints.aiomanager.token_store.resolve_alias", fake_resolve_alias)
    monkeypatch.setattr("app.api.endpoints.aiomanager.token_store.get_user_data", fake_get_user_data)


def _credentials(**overrides):
    # A stored record always carries a full settings body, so the fixture starts
    # from the real defaults rather than a hand-written stub.
    settings = get_default_settings().model_dump()
    settings.update({"aiomanager_instance_url": INSTANCE, "aiomanager_api_key": "user-key", **overrides})
    return {"settings": settings}


# --- the endpoint ------------------------------------------------------------


def test_a_connected_manager_is_pushed_this_installs_manifest(monkeypatch):
    _accounts(monkeypatch, _credentials())
    pushed = []

    async def fake_reinstall(instance_url, api_key, addon_url):
        pushed.append((instance_url, api_key, addon_url))
        return 12

    monkeypatch.setattr("app.api.endpoints.aiomanager.aiomanager_service.reinstall", fake_reinstall)

    response = client.post(f"/{TOKEN}/aiomanager/sync")

    assert response.status_code == 200
    assert response.json() == {"status": "synced", "addon_count": 12, "instance": "aiomanager.example.com"}
    instance_url, api_key, addon_url = pushed[0]
    assert (instance_url, api_key) == (INSTANCE, "user-key")
    assert addon_url.endswith(f"/{TOKEN}/manifest.json")


def test_an_account_without_a_manager_is_told_so_not_failed(monkeypatch):
    _accounts(monkeypatch, {"settings": {}})

    response = client.post(f"/{TOKEN}/aiomanager/sync")

    assert response.status_code == 409
    assert "AIOManager" in response.json()["detail"]


def test_a_manifest_is_never_pushed_from_an_unconfigured_account(monkeypatch):
    _accounts(monkeypatch, _credentials(aiomanager_api_key=None))
    pushed = []

    async def fake_reinstall(instance_url, api_key, addon_url):
        pushed.append(addon_url)

    monkeypatch.setattr("app.api.endpoints.aiomanager.aiomanager_service.reinstall", fake_reinstall)

    assert client.post(f"/{TOKEN}/aiomanager/sync").status_code == 409
    assert pushed == []


def test_a_malformed_token_is_rejected_before_anything_else(monkeypatch):
    _accounts(monkeypatch, _credentials())

    response = client.post("/not a token/aiomanager/sync")

    assert response.status_code == 400


def test_an_unknown_token_is_not_found(monkeypatch):
    _accounts(monkeypatch, _credentials())

    response = client.post("/some-other-token/aiomanager/sync")

    assert response.status_code == 404


def test_a_rejected_key_reaches_the_page_as_a_401(monkeypatch):
    _accounts(monkeypatch, _credentials())

    async def fake_reinstall(instance_url, api_key, addon_url):
        raise AIOManagerError("AIOManager rejected that API key.", status=401)

    monkeypatch.setattr("app.api.endpoints.aiomanager.aiomanager_service.reinstall", fake_reinstall)

    response = client.post(f"/{TOKEN}/aiomanager/sync")

    assert response.status_code == 401
    assert response.json()["detail"] == "AIOManager rejected that API key."


def test_validation_reports_an_unreachable_instance_without_saving(monkeypatch):
    def unreachable(method, url):
        raise httpx.ConnectError("refused", request=httpx.Request(method, url))

    service = AIOManagerService()
    monkeypatch.setattr(service, "client", FakeHydraClient(unreachable))
    monkeypatch.setattr("app.api.endpoints.aiomanager.aiomanager_service", service)

    response = client.post("/aiomanager/validate", json={"instance_url": INSTANCE, "api_key": "user-key"})

    assert response.status_code == 200
    assert response.json()["valid"] is False
    assert "Could not reach" in response.json()["message"]


# --- the service --------------------------------------------------------------


def test_a_manager_without_hydra_is_named_as_such(monkeypatch):
    # An instance too old for Hydra answers its single-page app: 200, HTML, no JSON.
    service = _service(monkeypatch, lambda method, url: {})

    with pytest.raises(AIOManagerError) as error:
        asyncio.run(service.probe(INSTANCE))

    assert "does not serve" in str(error.value)


def test_a_reinstall_that_answers_html_is_not_reported_as_synced(monkeypatch):
    service = _service(monkeypatch, lambda method, url: {} if method == "POST" else {"capabilities": ["addons"]})

    with pytest.raises(AIOManagerError) as error:
        asyncio.run(service.reinstall(INSTANCE, "user-key", f"https://watchly.example.com/{TOKEN}/manifest.json"))

    assert "does not serve" in str(error.value)


def test_the_pushed_url_has_no_doubled_slash_when_host_name_ends_in_one(monkeypatch):
    _accounts(monkeypatch, _credentials())
    pushed = []

    async def fake_reinstall(instance_url, api_key, addon_url):
        pushed.append(addon_url)
        return 1

    monkeypatch.setattr("app.api.endpoints.aiomanager.aiomanager_service.reinstall", fake_reinstall)
    monkeypatch.setattr("app.api.endpoints.aiomanager.settings.HOST_NAME", "https://watchly.example.com/")

    response = client.post(f"/{TOKEN}/aiomanager/sync")

    assert response.status_code == 200
    assert pushed == [f"https://watchly.example.com/{TOKEN}/manifest.json"]


def test_a_host_that_serves_no_manager_is_named_as_such(monkeypatch):
    def handler(method, url):
        raise _http_error(404, url=url, method="GET")

    service = _service(monkeypatch, handler)

    with pytest.raises(AIOManagerError) as error:
        asyncio.run(service.probe(INSTANCE))

    assert "not an AIOManager instance" in str(error.value)


def test_a_rotated_key_is_explained_as_such(monkeypatch):
    def handler(method, url):
        raise _http_error(401)

    service = _service(monkeypatch, handler)

    with pytest.raises(AIOManagerError) as error:
        asyncio.run(service.reinstall(INSTANCE, "stale-key", f"https://watchly.example.com/{TOKEN}/manifest.json"))

    assert error.value.status == 401
    assert "API Key tab" in str(error.value)


def test_a_rate_limited_account_is_told_to_wait(monkeypatch):
    def handler(method, url):
        raise _http_error(429)

    service = _service(monkeypatch, handler)

    with pytest.raises(AIOManagerError) as error:
        asyncio.run(service.reinstall(INSTANCE, "user-key", f"https://watchly.example.com/{TOKEN}/manifest.json"))

    assert error.value.status == 429
    assert "Wait a minute" in str(error.value)


def test_an_upstream_refusal_keeps_its_own_message(monkeypatch):
    def handler(method, url):
        raise _http_error(400, body={"error": "bad_request", "message": "Invalid addon URL"})

    service = _service(monkeypatch, handler)

    with pytest.raises(AIOManagerError) as error:
        asyncio.run(service.reinstall(INSTANCE, "user-key", "https://watchly.example.com/x/manifest.json"))

    assert str(error.value) == "Invalid addon URL"


def test_a_failed_registration_does_not_fail_the_push(monkeypatch):
    def handler(method, url):
        if url.endswith("/register"):
            raise _http_error(500, url=url)
        if method == "POST":
            return {"addons": [{"name": "Watchly"}]}
        return {"capabilities": ["addons"]}

    service = _service(monkeypatch, handler)

    assert asyncio.run(service.reinstall(INSTANCE, "user-key", "https://watchly.example.com/t/manifest.json")) == 1


def test_a_pushed_addon_is_registered_so_the_user_sees_it_in_connections(monkeypatch):
    calls = []

    def handler(method, url):
        calls.append((method, url))
        return {"addons": []}

    service = _service(monkeypatch, handler)

    asyncio.run(service.reinstall(INSTANCE, "user-key", "https://watchly.example.com/t/manifest.json"))

    assert ("POST", f"{INSTANCE}/hydra/register") in calls


def test_the_key_is_checked_against_the_collection_not_a_write(monkeypatch):
    service = _service(monkeypatch, lambda method, url: {"addons": []})

    asyncio.run(service.check_key(INSTANCE, "user-key"))

    assert service.client.calls == [("GET", ADDONS_URL)]


# --- settings round-trip ------------------------------------------------------


def test_the_manager_key_is_stored_as_a_secret():
    assert "aiomanager_api_key" in _SECRET_SETTINGS_FIELDS


def test_a_save_that_only_carries_the_mark_keeps_the_stored_key():
    built = auth_service._build_user_settings(
        TokenRequest(aiomanager_instance_url=INSTANCE, aiomanager_api_key=STORED_SECRET_SENTINEL),
        {"aiomanager_api_key": "stored-key"},
    )

    assert built.aiomanager_api_key == "stored-key"
    assert built.aiomanager_instance_url == INSTANCE


def test_clearing_the_key_turns_the_manager_off():
    built = auth_service._build_user_settings(
        TokenRequest(aiomanager_instance_url=INSTANCE, aiomanager_api_key=""),
        {"aiomanager_api_key": "stored-key"},
    )

    assert built.aiomanager_api_key == ""
