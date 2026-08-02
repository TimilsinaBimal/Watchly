import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.core.errors import GENERIC_ERROR, register_exception_handlers

SECRET = "SUPER-SECRET-AUTHKEY"


class Body(BaseModel):
    count: int


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom")
    async def boom():
        auth_key = SECRET  # noqa: F841 — in frame, so a leaky handler would expose it
        raise RuntimeError(f"redis exploded while holding {SECRET}")

    @app.get("/teapot")
    async def teapot():
        raise HTTPException(status_code=418, detail="I am a teapot")

    @app.get("/unavailable")
    async def unavailable():
        raise HTTPException(status_code=503, detail="Storage temporarily unavailable.")

    @app.post("/validated")
    async def validated(body: Body):
        return {"count": body.count}

    # raise_server_exceptions=False so the handler's response is returned rather
    # than the exception being re-raised into the test.
    return TestClient(app, raise_server_exceptions=False)


def test_unexpected_error_becomes_a_generic_500(client):
    response = client.get("/boom")

    assert response.status_code == 500
    assert response.json() == {"detail": GENERIC_ERROR}


def test_unexpected_error_does_not_leak_internals(client):
    """The cause belongs in the log, not the response: three endpoints used to
    interpolate the exception straight into `detail`."""
    body = response_text = client.get("/boom").text

    assert SECRET not in body
    assert "redis exploded" not in response_text
    assert "RuntimeError" not in response_text
    assert "Traceback" not in response_text


def test_http_exceptions_keep_their_status_and_message(client):
    """These are deliberate answers, so the handler must not flatten them."""
    response = client.get("/teapot")

    assert response.status_code == 418
    assert response.json() == {"detail": "I am a teapot"}


def test_server_side_http_exceptions_pass_through_too(client):
    response = client.get("/unavailable")

    assert response.status_code == 503
    assert response.json() == {"detail": "Storage temporarily unavailable."}


def test_validation_errors_return_a_readable_detail(client):
    """FastAPI's default puts a list of pydantic errors in `detail`; the configure
    page renders that field as a string, so it showed up as [object Object]."""
    response = client.post("/validated", json={"count": "not-a-number"})

    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid request."}
    assert isinstance(response.json()["detail"], str)


def test_unmatched_routes_still_404(client):
    response = client.get("/no-such-route")

    assert response.status_code == 404


def test_handlers_are_registered_on_the_real_app():
    """Guards the wiring, not just the factory."""
    from starlette.exceptions import HTTPException as StarletteHTTPException

    from app.core.app import app

    assert Exception in app.exception_handlers
    assert StarletteHTTPException in app.exception_handlers
