from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse

from fastapi.middleware.cors import CORSMiddleware
from app.api.main import api_router
from app.config import settings
from app.services.catalog_updater import BackgroundCatalogUpdater
import logging
from loguru import logger
from pathlib import Path
import os

class InterceptHandler(logging.Handler):
    def emit(self, record):
        try:
            level = logger.level(record.levelname).name
        except Exception:
            level = record.levelno

        logger.opt(depth=6, exception=record.exc_info).log(level, record.getMessage())


logging.basicConfig(handlers=[InterceptHandler()], level=logging.INFO, force=True)


app = FastAPI(
    title="Watchly",
    description="Stremio catalog addon for movie and series recommendations",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files
BASE_DIR = Path(__file__).resolve().parent
static_dir = BASE_DIR / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


# Serve index.html at /configure and /{token}/configure
@app.get("/", response_class=HTMLResponse)
@app.get("/configure", response_class=HTMLResponse)
@app.get("/{token}/configure", response_class=HTMLResponse)
async def configure_page(token: str | None = None):
    index_path = static_dir / "index.html"
    if index_path.exists():
        html_content = index_path.read_text(encoding="utf-8")
        dynamic_announcement = os.getenv("ANNOUNCEMENT_HTML")
        if dynamic_announcement is None:
            dynamic_announcement = settings.ANNOUNCEMENT_HTML
        announcement_html = (dynamic_announcement or "").strip()
        snippet = ""
        if announcement_html:
            snippet = (
                "\n                <div class=\"announcement\">"
                f"{announcement_html}"
                "</div>"
            )
        html_content = html_content.replace("<!-- ANNOUNCEMENT_HTML -->", snippet, 1)
        return HTMLResponse(content=html_content, media_type="text/html")
    return HTMLResponse(
        content="Watchly API is running. Static files not found.",
        media_type="text/plain",
        status_code=200,
    )


app.include_router(api_router)


catalog_updater: BackgroundCatalogUpdater | None = None


@app.on_event("startup")
async def start_background_catalog_refresh() -> None:
    global catalog_updater
    if settings.AUTO_UPDATE_CATALOGS and settings.CATALOG_REFRESH_INTERVAL_SECONDS > 0:
        catalog_updater = BackgroundCatalogUpdater(
            interval_seconds=settings.CATALOG_REFRESH_INTERVAL_SECONDS
        )
        catalog_updater.start()
        logger.info(
            "Background catalog updates enabled (interval=%ss)",
            settings.CATALOG_REFRESH_INTERVAL_SECONDS,
        )


@app.on_event("shutdown")
async def stop_background_catalog_refresh() -> None:
    global catalog_updater
    if catalog_updater:
        await catalog_updater.stop()
        catalog_updater = None


# if __name__ == "__main__":
#     import uvicorn

#     uvicorn.run("main:app", host="0.0.0.0", port=settings.PORT, reload=True)
