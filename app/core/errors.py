from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from loguru import logger
from starlette.exceptions import HTTPException as StarletteHTTPException

# What a client sees when something failed in a way we didn't anticipate. The cause
# goes to the log instead: interpolating it into the response has previously exposed
# upstream error text and internal URLs.
GENERIC_ERROR = "Something went wrong. Please try again."


def register_exception_handlers(app: FastAPI) -> None:
    """Turn exceptions into responses in one place.

    Endpoints used to repeat this per route, which meant the routes that didn't —
    dashboard, manifest, status — returned a bare 500 with nothing logged at all.
    Handlers here cover every route, including ones added later.
    """

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        # Deliberate answers rather than faults, so they keep the status and message
        # the raising code chose. Logged only so failures are visible.
        log = logger.error if exc.status_code >= 500 else logger.warning
        log(f"{request.method} {request.url.path} -> {exc.status_code}: {exc.detail}")
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # FastAPI's default body puts a list of pydantic errors in `detail`. The
        # configure page renders `detail` as a string, so that surfaced to users as
        # "[object Object]".
        logger.warning(f"{request.method} {request.url.path} -> 422: {exc.errors()}")
        return JSONResponse(status_code=422, content={"detail": "Invalid request."})

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(f"{request.method} {request.url.path} -> unhandled {type(exc).__name__}: {exc}")
        return JSONResponse(status_code=500, content={"detail": GENERIC_ERROR})
