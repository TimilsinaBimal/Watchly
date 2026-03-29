import importlib

from fastapi.testclient import TestClient

from app.core.app import app

client = TestClient(app)
app_module = importlib.import_module("app.core.app")


def test_configure_page_bootstraps_current_year_and_year_defaults(monkeypatch):
    async def fake_fetch_languages_list():
        return [{"iso_639_1": "en-US", "language": "English", "country": "US"}]

    async def fake_count_users():
        return 7

    monkeypatch.setattr(app_module, "fetch_languages_list", fake_fetch_languages_list)
    monkeypatch.setattr(app_module.token_store, "count_users", fake_count_users)

    response = client.get("/configure")

    assert response.status_code == 200
    html = response.text
    assert 'window.YEAR_RANGE_DEFAULTS = {"min": 1970, "max": ' in html
    assert 'id="yearMin" min="1970"' in html
    assert 'id="yearMax" min="1970"' in html
