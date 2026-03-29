from fastapi.testclient import TestClient

from app.core.app import app
from app.services.recommendation.catalog_service import catalog_service

client = TestClient(app)


def test_catalog_endpoint_keeps_cache_header_for_non_empty_results(monkeypatch):
    async def fake_get_catalog(token: str, content_type: str, catalog_id: str):
        return {"metas": [{"id": "tt1234567", "type": "movie", "name": "Example"}]}, {"Cache-Control": "public"}

    monkeypatch.setattr(catalog_service, "get_catalog", fake_get_catalog)

    response = client.get("/abc/catalog/movie/watchly.rec.json")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "public"
    assert response.json()["metas"]


def test_catalog_endpoint_marks_empty_results_as_no_cache(monkeypatch):
    async def fake_get_catalog(token: str, content_type: str, catalog_id: str):
        return {"metas": []}, {"Cache-Control": "public"}

    monkeypatch.setattr(catalog_service, "get_catalog", fake_get_catalog)

    response = client.get("/abc/catalog/movie/watchly.rec.json")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-cache"
    assert response.json() == {"metas": []}
