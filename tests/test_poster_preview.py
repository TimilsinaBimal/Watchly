from fastapi.testclient import TestClient

from app.api.endpoints import validation
from app.core.app import app
from app.core.security import STORED_SECRET_SENTINEL

client = TestClient(app)

TEMPLATE = "https://posters.example/{api_key}/{type}/{imdb_id}.jpg?lang={language_short}&l={language}"
KNOWN_TOKEN = "acct_token_1"


def _fake_store(monkeypatch, poster_rating):
    async def resolve_alias(token):
        return token

    async def get_user_data(token):
        if token != KNOWN_TOKEN:
            return None
        return {"settings": {"poster_rating": poster_rating}}

    monkeypatch.setattr(validation.token_store, "resolve_alias", resolve_alias)
    monkeypatch.setattr(validation.token_store, "get_user_data", get_user_data)


def test_fresh_key_fills_every_placeholder():
    response = client.post(
        "/poster-rating/preview", json={"url_template": TEMPLATE, "api_key": "fresh-key", "language": "de-DE"}
    )

    assert response.status_code == 200
    assert response.json() == [
        {
            "title": "Interstellar",
            "type": "movie",
            "url": "https://posters.example/fresh-key/movie/tt0816692.jpg?lang=de&l=de-DE",
        },
        {
            "title": "Breaking Bad",
            "type": "series",
            "url": "https://posters.example/fresh-key/series/tt0903747.jpg?lang=de&l=de-DE",
        },
    ]


def test_marker_uses_the_saved_key_for_that_account(monkeypatch):
    _fake_store(monkeypatch, {"provider": "custom", "api_key": "saved-key", "url_template": TEMPLATE})

    response = client.post(
        "/poster-rating/preview",
        json={"url_template": TEMPLATE, "api_key": STORED_SECRET_SENTINEL, "token": KNOWN_TOKEN},
    )

    assert response.status_code == 200
    urls = [p["url"] for p in response.json()]
    assert all("/saved-key/" in url for url in urls)
    assert not any(STORED_SECRET_SENTINEL in url for url in urls)


def test_marker_with_unknown_token_is_rejected(monkeypatch):
    _fake_store(monkeypatch, {"provider": "custom", "api_key": "saved-key", "url_template": TEMPLATE})

    response = client.post(
        "/poster-rating/preview",
        json={"url_template": TEMPLATE, "api_key": STORED_SECRET_SENTINEL, "token": "someone_else"},
    )

    assert response.status_code == 404


def test_marker_without_token_is_rejected():
    response = client.post("/poster-rating/preview", json={"url_template": TEMPLATE, "api_key": STORED_SECRET_SENTINEL})

    assert response.status_code == 400


def test_marker_does_not_hand_out_another_providers_key(monkeypatch):
    _fake_store(monkeypatch, {"provider": "rpdb", "api_key": "rpdb-key"})

    response = client.post(
        "/poster-rating/preview",
        json={"url_template": TEMPLATE, "api_key": STORED_SECRET_SENTINEL, "token": KNOWN_TOKEN},
    )

    assert response.status_code == 400
    assert "rpdb-key" not in response.text


def test_template_without_imdb_id_is_a_clear_400():
    response = client.post("/poster-rating/preview", json={"url_template": "https://posters.example/{type}.jpg"})

    assert response.status_code == 400
    assert response.json() == {"detail": "custom poster url_template must contain {imdb_id}"}


def test_non_http_template_is_a_clear_400():
    response = client.post("/poster-rating/preview", json={"url_template": "not a url {imdb_id}"})

    assert response.status_code == 400
    assert response.json() == {"detail": "custom poster provider needs an http(s) url_template"}
