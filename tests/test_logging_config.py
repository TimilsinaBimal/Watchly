import sys

from loguru import logger

from app.core.logging import configure_logging

SECRET = "PASSWORD-LEAK-hunter2"


def log_a_failure_holding_a_secret() -> None:
    """Mirrors stremio/auth.py: a payload with credentials is in frame across the
    call that raises, and the handler logs the traceback."""
    payload = {"email": "someone@example.com", "password": SECRET}
    try:
        _post(payload)
    except Exception as e:
        logger.exception(f"Failed to login to Stremio: {e}")


def _post(payload):
    raise RuntimeError("connection reset")


def test_tracebacks_do_not_print_variable_values(capsys, monkeypatch):
    """loguru's default handler runs with diagnose=True, which annotates each frame
    with the values of the variables it references — so a login failure wrote the
    user's password to the log. The entire fix is one argument, and it would fail
    silently if it regressed, so assert on the output rather than the config."""
    monkeypatch.setattr("app.core.logging.settings.LOG_LEVEL", "DEBUG")
    configure_logging()

    log_a_failure_holding_a_secret()

    output = capsys.readouterr().err
    assert SECRET not in output
    assert "someone@example.com" not in output
    # The failure itself is still reported, with a frame chain to locate it.
    assert "Failed to login to Stremio" in output
    assert "connection reset" in output
    assert "Traceback" in output


def test_level_filters_debug_out(capsys, monkeypatch):
    monkeypatch.setattr("app.core.logging.settings.LOG_LEVEL", "INFO")
    configure_logging()

    logger.debug("cache hit for token")
    logger.info("catalog served")

    output = capsys.readouterr().err
    assert "cache hit for token" not in output
    assert "catalog served" in output


def test_debug_level_lets_debug_through(capsys, monkeypatch):
    monkeypatch.setattr("app.core.logging.settings.LOG_LEVEL", "DEBUG")
    configure_logging()

    logger.debug("cache hit for token")

    assert "cache hit for token" in capsys.readouterr().err


def test_levels_are_labelled(capsys, monkeypatch):
    monkeypatch.setattr("app.core.logging.settings.LOG_LEVEL", "DEBUG")
    configure_logging()

    logger.info("an info line")
    logger.warning("a warning line")
    logger.error("an error line")

    output = capsys.readouterr().err
    assert "INFO" in output and "an info line" in output
    assert "WARNING" in output and "a warning line" in output
    assert "ERROR" in output and "an error line" in output


def test_request_id_tags_every_line_from_that_request(capsys, monkeypatch):
    """Messages carry a redacted token, which identifies the account but not the
    request — and Stremio asks for every row at once, so one account's lines
    interleave with no way to tell them apart."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.core.logging import register_request_id_middleware

    monkeypatch.setattr("app.core.logging.settings.LOG_LEVEL", "INFO")
    configure_logging()

    app = FastAPI()
    register_request_id_middleware(app)

    @app.get("/probe")
    async def probe():
        logger.info("deep inside the route")
        return {"ok": True}

    response = TestClient(app).get("/probe")
    request_id = response.headers["X-Request-ID"]

    assert request_id
    output = capsys.readouterr().err
    assert f"| {request_id} |" in output
    assert "deep inside the route" in output


def test_a_supplied_request_id_is_honoured(capsys, monkeypatch):
    """So an id assigned upstream, by a proxy or the client, survives into our logs."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.core.logging import register_request_id_middleware

    monkeypatch.setattr("app.core.logging.settings.LOG_LEVEL", "INFO")
    configure_logging()

    app = FastAPI()
    register_request_id_middleware(app)

    @app.get("/probe")
    async def probe():
        logger.info("handled")
        return {"ok": True}

    response = TestClient(app).get("/probe", headers={"X-Request-ID": "from-upstream"})

    assert response.headers["X-Request-ID"] == "from-upstream"
    assert "| from-upstream |" in capsys.readouterr().err


def test_lines_outside_a_request_still_render(capsys, monkeypatch):
    """Startup and background work have no request; the field needs a default or the
    format string raises."""
    monkeypatch.setattr("app.core.logging.settings.LOG_LEVEL", "INFO")
    configure_logging()

    logger.info("started up")

    assert "| - |" in capsys.readouterr().err


def teardown_module() -> None:
    """Leave loguru writing to the real stderr for the rest of the suite."""
    logger.remove()
    logger.add(sys.stderr)
