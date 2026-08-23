"""Logging setup, and the levels the rest of the app is expected to use.

- debug     per-item and per-request detail: cache hits, counts, which row is being
            served. Off in production, so it can be as chatty as is useful.
- info      one line per meaningful outcome, not per step. A catalog built from
            scratch, a profile rebuilt, a warm-up finished.
- warning   degraded but handled: a fallback was taken, a provider was unreachable,
            a stale token was dropped.
- error     the request failed or work was lost.
- exception only where the traceback is actionable. An expected condition — an
            unsupported language, a title TMDB doesn't know — is a warning.

The test for whether something is info: would you want one line per row per home
screen open? Stremio requests every enabled row at once, so anything on that path
is multiplied by a dozen.
"""

import sys
import uuid

from fastapi import FastAPI, Request
from loguru import logger

from app.core.config import settings

# loguru's default format minus the markup, so it reads the same piped to a file,
# plus the request id every line inside a request carries.
LOG_FORMAT = "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {extra[request_id]} | {name}:{function}:{line} - {message}"

# Lines emitted outside a request — startup, scheduled work — still need the field.
NO_REQUEST = "-"

REQUEST_ID_HEADER = "X-Request-ID"


def configure_logging() -> None:
    """Replace loguru's default handler with a configured one.

    Nothing configured loguru before, so the app ran on its defaults: every debug
    line emitted regardless of environment, and — the reason this matters —
    `diagnose=True`, which annotates tracebacks with the *values* of variables in
    the failing frame.

    That is a credential leak here. `stremio/auth.py` holds a payload containing the
    user's email and password across the call that can raise, and the handler logs
    the traceback; the same is true anywhere decrypted API keys are in scope. Turning
    diagnose off is the whole point of this module.
    """
    logger.configure(extra={"request_id": NO_REQUEST})
    logger.remove()
    logger.add(
        sys.stderr,
        level=settings.LOG_LEVEL,
        format=LOG_FORMAT,
        # Never on: it prints variable values from every frame in the traceback.
        diagnose=False,
        # The frame chain is still useful, and it carries no user data.
        backtrace=True,
        enqueue=False,
    )


def register_request_id_middleware(app: FastAPI) -> None:
    """Tag every line emitted during a request with the same id.

    Messages already carry a redacted token, which identifies the account but not
    the request — and Stremio asks for every row at once, so one account's lines
    interleave with no way to tell which request produced which. The id is returned
    in a header too, so a user reporting a problem can quote it.

    Background work started during a request inherits the id, because a task copies
    the current context when it is created. A stale-row refresh therefore stays
    attributable to the request that triggered it.
    """

    @app.middleware("http")
    async def add_request_id(request: Request, call_next):
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex[:12]
        with logger.contextualize(request_id=request_id):
            response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response
