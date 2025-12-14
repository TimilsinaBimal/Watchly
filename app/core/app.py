import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

from cachetools import TTLCache
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from app.api.main import api_router
from app.services.catalog_updater import BackgroundCatalogUpdater
from app.services.token_store import token_store
from app.startup.migration import migrate_tokens

from .config import settings
from .version import __version__

# class InterceptHandler(logging.Handler):
#     def emit(self, record):
#         try:
#             level = logger.level(record.levelname).name
#         except Exception:
#             level = record.levelno

#         logger.opt(depth=6, exception=record.exc_info).log(level, record.getMessage())


# logging.basicConfig(handlers=[InterceptHandler()], level=logging.INFO, force=True)

# Global catalog updater instance
catalog_updater: BackgroundCatalogUpdater | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manage application lifespan events (startup/shutdown).
    """
    global catalog_updater

    if settings.HOST_NAME.lower() != "https://1ccea4301587-watchly.baby-beamup.club":
        task = asyncio.create_task(migrate_tokens())

        # Ensure background exceptions are surfaced in logs
        def _on_done(t: asyncio.Task):
            try:
                t.result()
            except Exception as exc:
                logger.error(f"migrate_tokens background task failed: {exc}")

        task.add_done_callback(_on_done)

    # Startup
    if settings.AUTO_UPDATE_CATALOGS:
        catalog_updater = BackgroundCatalogUpdater()
        catalog_updater.start()
    yield

    # Shutdown
    if catalog_updater:
        await catalog_updater.stop()
        catalog_updater = None
        logger.info("Background catalog updates stopped")
    # Close shared token store Redis client
    try:
        await token_store.close()
        logger.info("TokenStore Redis client closed")
    except Exception as exc:
        logger.warning(f"Failed to close TokenStore Redis client: {exc}")


if settings.APP_ENV != "development":
    lifespan = lifespan
else:
    lifespan = None

app = FastAPI(
    title="Watchly",
    description="Stremio catalog addon for movie and series recommendations",
    version=__version__,
    lifespan=lifespan,
    docs_url=None if settings.APP_ENV != "development" else "/docs",
    redoc_url=None if settings.APP_ENV != "development" else "/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Simple IP-based rate limiter for repeated probes of missing tokens.
# Tracks recent failure counts per IP to avoid expensive repeated requests.
_ip_failure_cache: TTLCache = TTLCache(maxsize=10000, ttl=600)
_IP_FAILURE_THRESHOLD = 8


@app.middleware("http")
async def block_missing_token_middleware(request: Request, call_next):
    # Extract first path segment which is commonly the token in addon routes
    path = request.url.path.lstrip("/")
    seg = path.split("/", 1)[0] if path else ""
    try:
        # If token is known-missing, short-circuit and track IP failures
        if seg and seg in token_store._missing_tokens:
            ip = request.client.host if request.client else "unknown"
            try:
                _ip_failure_cache[ip] = _ip_failure_cache.get(ip, 0) + 1
            except Exception:
                pass
            if _ip_failure_cache.get(ip, 0) > _IP_FAILURE_THRESHOLD:
                return HTMLResponse(content="Too many requests", status_code=429)
            return HTMLResponse(content="Invalid token", status_code=401)
    except Exception:
        pass
    return await call_next(request)


# Serve static files
# Static directory is at project root (3 levels up from app/core/app.py)
# app/core/app.py -> app/core -> app -> root
project_root = Path(__file__).resolve().parent.parent.parent
static_dir = project_root / "app/static"

if static_dir.exists():
    app.mount("/app/static", StaticFiles(directory=str(static_dir)), name="static")


# Serve index.html at /configure and /{token}/configure
@app.get("/", response_class=HTMLResponse)
@app.get("/configure", response_class=HTMLResponse)
@app.get("/{token}/configure", response_class=HTMLResponse)
async def configure_page(token: str | None = None):
    index_path = static_dir / "index.html"
    if index_path.exists():
        with open(index_path, encoding="utf-8") as file:
            html_content = file.read()
        dynamic_announcement = os.getenv("ANNOUNCEMENT_HTML")
        if dynamic_announcement is None:
            dynamic_announcement = settings.ANNOUNCEMENT_HTML
        announcement_html = (dynamic_announcement or "").strip()
        snippet = ""
        if announcement_html:
            snippet = f'\n                <div class="announcement">{announcement_html}</div>'
        html_content = html_content.replace("<!-- ANNOUNCEMENT_HTML -->", snippet, 1)
        # Inject version
        html_content = html_content.replace("<!-- APP_VERSION -->", __version__, 1)
        # Inject host
        html_content = html_content.replace("<!-- APP_HOST -->", settings.HOST_NAME, 1)
        return HTMLResponse(content=html_content, media_type="text/html")
    return HTMLResponse(
        content="Watchly API is running. Static files not found.",
        media_type="text/plain",
        status_code=200,
    )


app.include_router(api_router)
