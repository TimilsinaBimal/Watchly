import json
from contextlib import asynccontextmanager
from pathlib import Path

from cachetools import TTLCache
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader
from loguru import logger

from app.api.endpoints.meta import fetch_languages_list
from app.api.main import api_router
from app.core.settings import get_default_catalogs_for_frontend
from app.services.redis_service import redis_service
from app.services.tmdb.genre import movie_genres, series_genres
from app.services.token_store import token_store

from .config import settings
from .version import __version__

project_root = Path(__file__).resolve().parent.parent.parent
static_dir = project_root / "app/static"
templates_dir = project_root / "app/templates"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manage application lifespan events (startup/shutdown).
    """
    yield
    try:
        await redis_service.close()
        logger.info("Redis client closed")
    except Exception as exc:
        logger.warning(f"Failed to close Redis client: {exc}")


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

_ip_failure_cache: TTLCache = TTLCache(maxsize=10000, ttl=600)
IP_FAILURE_THRESHOLD = 8


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
            if _ip_failure_cache.get(ip, 0) > IP_FAILURE_THRESHOLD:
                return HTMLResponse(content="Too many requests", status_code=429)
            return HTMLResponse(content="Invalid token", status_code=401)
    except Exception:
        pass
    return await call_next(request)


if static_dir.exists():
    app.mount("/app/static", StaticFiles(directory=str(static_dir)), name="static")

# Initialize Jinja2 templates
jinja_env = Environment(loader=FileSystemLoader(str(templates_dir)))
jinja_env.filters["tojson"] = lambda v: json.dumps(v)


@app.get("/", response_class=HTMLResponse)
@app.get("/configure", response_class=HTMLResponse)
@app.get("/{token}/configure", response_class=HTMLResponse)
async def configure_page(request: Request, _token: str | None = None):
    languages = []
    try:
        languages = await fetch_languages_list()
    except Exception as e:
        logger.warning(f"Failed to fetch languages for template: {e}")
        languages = [{"iso_639_1": "en-US", "language": "English", "country": "US"}]

    # Format default catalogs for frontend
    default_catalogs = get_default_catalogs_for_frontend()

    # Format genres for frontend
    movie_genres_list = [{"id": str(id), "name": name} for id, name in movie_genres.items()]
    series_genres_list = [{"id": str(id), "name": name} for id, name in series_genres.items()]

    template = jinja_env.get_template("index.html")
    html_content = template.render(
        request=request,
        app_version=__version__,
        app_host=settings.HOST_NAME,
        announcement_html=settings.ANNOUNCEMENT_HTML or "",
        languages=languages,
        default_catalogs=default_catalogs,
        movie_genres=movie_genres_list,
        series_genres=series_genres_list,
    )
    return HTMLResponse(content=html_content, media_type="text/html")


app.include_router(api_router)
