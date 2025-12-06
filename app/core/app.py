import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from app.api.main import api_router
from app.services.catalog_updater import BackgroundCatalogUpdater

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


if settings.APP_ENV != "development":
    lifespan = lifespan
else:
    lifespan = None

app = FastAPI(
    title="Watchly",
    description="Stremio catalog addon for movie and series recommendations",
    version=__version__,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
