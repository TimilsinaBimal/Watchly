import asyncio
import time
from types import SimpleNamespace

import httpx
import pytest
from pydantic import ValidationError

from app.api.models.tokens import TokenRequest
from app.core.settings import UserSettings
from app.services.auth import AuthService
from app.services.recommendation import catalog_service as cs
from app.services.recommendation import imdb_ratings


@pytest.mark.parametrize("value", [-0.1, 10.1, float("nan"), float("inf")])
def test_invalid_minimum_is_rejected(value):
    for model in (TokenRequest, UserSettings):
        with pytest.raises(ValidationError):
            model(catalogs=[], imdb_rating_min=value)


@pytest.mark.parametrize("value", [None, 0, 7.5, 10])
def test_minimum_survives_settings_round_trip(value):
    payload = TokenRequest(imdb_rating_min=value)
    settings = AuthService()._build_user_settings(payload)
    assert UserSettings.model_validate(settings.model_dump()).imdb_rating_min == value


def test_disabled_filter_makes_no_requests(monkeypatch):
    def unexpected_client(**kwargs):
        pytest.fail("Disabled filter must not create a client")

    monkeypatch.setattr(imdb_ratings, "BaseClient", unexpected_client)
    metas = [{"id": "tt1", "imdbRating": "8.9"}]
    assert asyncio.run(imdb_ratings.filter_by_imdb_rating(metas, "movie", None)) is metas


@pytest.mark.parametrize("content_type", ["movie", "series"])
def test_filter_uses_imdb_inclusive_boundary_and_preserves_order(monkeypatch, content_type):
    ratings = {"tt1": "7.4", "tt2": "7.5", "tt3": "9.1", "tt4": None, "tt5": "N/A", "tt6": "nan", "tt7": "11"}
    calls = []
    closed = []

    class Client:
        def __init__(self, **kwargs):
            pass

        async def get(self, path):
            calls.append(path)
            return {"meta": {"imdbRating": ratings[path.split("/")[-1].split(".")[0]]}}

        async def close(self):
            closed.append(True)

    monkeypatch.setattr(imdb_ratings, "BaseClient", Client)
    metas = [{"id": key, "imdbRating": "10"} for key in ratings] + [{"id": "tmdb:99"}]
    result = asyncio.run(imdb_ratings.filter_by_imdb_rating(metas, content_type, 7.5))
    assert [m["id"] for m in result] == ["tt2", "tt3"]
    assert result[0]["imdbRating"] == "7.5"
    assert metas[1]["imdbRating"] == "10"
    assert all(path.startswith(f"/meta/{content_type}/") for path in calls)
    assert closed == [True]


@pytest.mark.parametrize("status", [404, 503])
def test_missing_metadata_excluded_but_outages_raise_and_close(monkeypatch, status):
    closed = []

    class Client:
        def __init__(self, **kwargs):
            pass

        async def get(self, path):
            response = httpx.Response(status, request=httpx.Request("GET", "https://example.com"))
            response.raise_for_status()

        async def close(self):
            closed.append(True)

    monkeypatch.setattr(imdb_ratings, "BaseClient", Client)

    def run():
        return asyncio.run(imdb_ratings.filter_by_imdb_rating([{"id": "tt1"}], "movie", 7))

    if status == 404:
        assert run() == []
    else:
        with pytest.raises(httpx.HTTPStatusError):
            run()
    assert closed == [True]


def test_cached_catalog_is_served_without_rating_requests(monkeypatch):
    cached_body = {"metas": [{"id": "tt1"}, {"id": "tt2"}]}

    async def alias(token):
        return token

    async def credentials(token):
        return {"settings": UserSettings(catalogs=[], imdb_rating_min=7.5).model_dump()}

    async def cached(*args):
        return cached_body, int(time.time())

    async def filter_metas(*args):
        pytest.fail("Cached rows are already filtered; a hit must not call Cinemeta")

    monkeypatch.setattr(cs.settings, "AUTO_UPDATE_CATALOGS", False)
    monkeypatch.setattr(cs.token_store, "resolve_alias", alias)
    monkeypatch.setattr(cs.token_store, "get_user_data", credentials)
    monkeypatch.setattr(cs.user_cache, "get_catalog", cached)
    monkeypatch.setattr(cs, "filter_by_imdb_rating", filter_metas)
    data, _ = asyncio.run(cs.CatalogService().get_catalog("token", "series", "watchly.rewatch"))
    assert data["metas"] == [{"id": "tt1"}, {"id": "tt2"}]


@pytest.mark.parametrize("outage", [False, True])
def test_cold_catalog_filters_before_cache_write(monkeypatch, outage):
    service = cs.CatalogService()
    settings = UserSettings(catalogs=[], imdb_rating_min=7.5)
    ctx = SimpleNamespace(token="token", user_settings=settings, library=None)
    writes = []

    async def resolve(*args):
        return "watchly.rec"

    async def profile(*args):
        return SimpleNamespace(source="stremio"), set(), set()

    async def recommendations(**kwargs):
        return [{"id": "tt1", "type": "movie", "name": "Low"}, {"id": "tt2", "type": "movie", "name": "High"}]

    async def filter_metas(metas, content_type, minimum):
        assert minimum == 7.5
        if outage:
            raise httpx.ConnectError("Cinemeta unavailable")
        return metas[1:]

    async def write(*args):
        writes.append(args[3])

    monkeypatch.setattr(service, "_resolve_slot", resolve)
    monkeypatch.setattr(service, "_initialize_services", lambda _: {"profile": None})
    monkeypatch.setattr(service, "_get_recommendations", recommendations)
    monkeypatch.setattr(cs.user_cache, "get_profile_and_watched_sets", profile)
    monkeypatch.setattr(cs.user_cache, "set_catalog", write)
    monkeypatch.setattr(cs, "filter_by_imdb_rating", filter_metas)
    data, _ = asyncio.run(service._build_catalog(ctx, "movie", "watchly.rec", {}))
    assert [m["id"] for m in data["metas"]] == ([] if outage else ["tt2"])
    assert writes == ([] if outage else [data])
