import asyncio

import httpx
import pytest

from app.core.settings import get_default_settings
from app.services.profile.service import ProfileService

TOKEN = "tok_trakt_history_failures"
GOOD_ACCESS_TOKEN = "good-access-token"


def trakt_rejecting(status: int):
    """A Trakt that answers only the good token; anything else gets `status`."""

    async def get_history(access_token: str):
        if access_token == GOOD_ACCESS_TOKEN:
            raise AssertionError("the good token must not reach this test")
        request = httpx.Request("GET", "https://api.trakt.tv/users/me/watched/movies")
        raise httpx.HTTPStatusError("rejected", request=request, response=httpx.Response(status, request=request))

    return get_history


def settings_with_trakt_token(access_token: str):
    user_settings = get_default_settings()
    user_settings.watch_history_source = "trakt"
    user_settings.trakt_access_token = access_token
    return user_settings


@pytest.fixture
def cleared(monkeypatch):
    calls: list[tuple[str, str]] = []

    async def record(self, token, source):
        calls.append((token, source))

    monkeypatch.setattr(ProfileService, "_clear_revoked_token", record)
    return calls


def test_a_rejected_token_is_cleared_and_yields_no_history(monkeypatch, cleared):
    monkeypatch.setattr("app.services.trakt.trakt_service.get_history", trakt_rejecting(401))

    history, missing, revoked = asyncio.run(
        ProfileService().fetch_external_watch_history("trakt", settings_with_trakt_token("stale"), TOKEN)
    )

    assert history is None
    assert revoked and not missing
    assert cleared == [(TOKEN, "trakt")]


def test_a_trakt_outage_keeps_the_token_and_yields_no_history(monkeypatch, cleared):
    monkeypatch.setattr("app.services.trakt.trakt_service.get_history", trakt_rejecting(503))

    history, missing, revoked = asyncio.run(
        ProfileService().fetch_external_watch_history("trakt", settings_with_trakt_token("fine"), TOKEN)
    )

    assert history is None
    assert not revoked and not missing
    assert cleared == []


def test_a_failed_refresh_after_401_keeps_the_token(monkeypatch, cleared):
    """Trakt rotates refresh tokens: a concurrent request may already have spent this one."""
    monkeypatch.setattr("app.services.trakt.trakt_service.get_history", trakt_rejecting(401))

    async def refresh_lost(self, token, refresh_token):
        return None

    monkeypatch.setattr(ProfileService, "_refresh_trakt_token", refresh_lost)
    user_settings = settings_with_trakt_token("stale")
    user_settings.trakt_refresh_token = "spent-elsewhere"

    history, missing, revoked = asyncio.run(
        ProfileService().fetch_external_watch_history("trakt", user_settings, TOKEN)
    )

    assert history is None
    assert not revoked and not missing
    assert cleared == []
