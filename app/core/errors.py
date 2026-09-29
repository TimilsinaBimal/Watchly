from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from loguru import logger
from starlette.exceptions import HTTPException as StarletteHTTPException

# What a client sees when something failed in a way we didn't anticipate. The cause
# goes to the log instead: interpolating it into the response has previously exposed
# upstream error text and internal URLs.
GENERIC_ERROR = "Something went wrong. Please try again."


def _route(request: Request) -> str:
    # The route template, not the path: authenticated paths embed the user's token.
    route = request.scope.get("route")
    return route.path if route else "<unmatched route>"


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        # Deliberate answers rather than faults, so they keep the status and message
        # the raising code chose. Logged only so failures are visible.
        log = logger.error if exc.status_code >= 500 else logger.warning
        log(f"{request.method} {_route(request)} -> {exc.status_code}: {exc.detail}")
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # FastAPI's default body puts a list of pydantic errors in `detail`. The
        # configure page renders `detail` as a string, so that surfaced to users as
        # "[object Object]".
        # Log loc and type only: each error's `input` echoes the rejected value, which
        # can be a password.
        errors = [(e["loc"], e["type"]) for e in exc.errors()]
        logger.warning(f"{request.method} {_route(request)} -> 422: {errors}")
        return JSONResponse(status_code=422, content={"detail": "Invalid request."})

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(f"{request.method} {_route(request)} -> unhandled {type(exc).__name__}")
        return JSONResponse(status_code=500, content={"detail": GENERIC_ERROR})
