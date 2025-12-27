from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader
from loguru import logger

from app.api.endpoints.meta import fetch_languages_list
from app.api.main import api_router
from app.services.token_store import token_store

from .config import settings
from .version import __version__


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manage application lifespan events (startup/shutdown).
    """
    yield
    try:
        await token_store.close()
        logger.info("TokenStore Redis client closed")
    except Exception as exc:
        logger.warning(f"Failed to close TokenStore Redis client: {exc}")


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
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Serve static files
# app/core/app.py -> app/core -> app -> root
project_root = Path(__file__).resolve().parent.parent.parent
static_dir = project_root / "app/static"
templates_dir = project_root / "app/templates"

if static_dir.exists():
    app.mount("/app/static", StaticFiles(directory=str(static_dir)), name="static")

# Initialize Jinja2 templates
jinja_env = Environment(loader=FileSystemLoader(str(templates_dir)))


# Serve index.html at /configure and /{token}/configure
@app.get("/", response_class=HTMLResponse)
@app.get("/configure", response_class=HTMLResponse)
@app.get("/{token}/configure", response_class=HTMLResponse)
async def configure_page(request: Request, token: str | None = None):
    languages = []
    try:
        languages = await fetch_languages_list()
    except Exception as e:
        logger.warning(f"Failed to fetch languages for template: {e}")
        languages = [{"iso_639_1": "en-US", "language": "English", "country": "US"}]

    template = jinja_env.get_template("index.html")
    html_content = template.render(
        request=request,
        app_version=__version__,
        app_host=settings.HOST_NAME,
        announcement_html=settings.ANNOUNCEMENT_HTML or "",
        languages=languages,
    )
    return HTMLResponse(content=html_content, media_type="text/html")


app.include_router(api_router)
