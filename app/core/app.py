import json
from contextlib import asynccontextmanager
from pathlib import Path

import markdown
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader
from loguru import logger

from app.api.endpoints.languages import fetch_languages_list
from app.api.router import api_router
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging, register_request_id_middleware
from app.core.security import STORED_SECRET_SENTINEL
from app.core.settings import MAX_ITEM_ROWS, get_current_year, get_default_catalogs_for_frontend, get_default_year_range
from app.services.redis_service import redis_service
from app.services.tmdb.genre import movie_genres, series_genres
from app.services.token_store import token_store

from .config import settings
from .version import __version__

configure_logging()

project_root = Path(__file__).resolve().parent.parent.parent
static_dir = project_root / "app/static"
templates_dir = project_root / "app/templates"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manage application lifespan events (startup/shutdown).
    """
    # Startup checks
    if settings.APP_ENV == "production" and (not settings.TOKEN_SALT or settings.TOKEN_SALT == "change-me"):
        raise RuntimeError(
            "TOKEN_SALT is unset or using the insecure default 'change-me' in production. "
            "Set the TOKEN_SALT environment variable to a strong, unique value before starting the app."
        )

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
    docs_url=None if settings.APP_ENV not in ["development", "vercel"] else "/docs",
    redoc_url=None if settings.APP_ENV != "development" else "/redoc",
)

register_exception_handlers(app)
register_request_id_middleware(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class RevalidatedStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope) -> Response:
        # Browsers cache each ES module separately, so without this a deploy can
        # leave a stale modules/*.js running against a newer backend (#167).
        # no-cache still allows caching but forces an ETag revalidation, which
        # is a 304 until the file actually changes.
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


if static_dir.exists():
    app.mount("/app/static", RevalidatedStaticFiles(directory=str(static_dir)), name="static")

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

    # Get total users count
    total_users = 0
    try:
        total_users = await token_store.count_users()
    except Exception as e:
        logger.warning(f"Failed to get total users for template: {e}")

    # Format default catalogs for frontend
    default_catalogs = get_default_catalogs_for_frontend()
    year_range_defaults = get_default_year_range()

    # Format genres for frontend
    movie_genres_list = [{"id": str(id), "name": name} for id, name in movie_genres.items()]
    series_genres_list = [{"id": str(id), "name": name} for id, name in series_genres.items()]

    template = jinja_env.get_template("index.html")
    html_content = template.render(
        request=request,
        app_version=__version__,
        total_users=total_users,
        app_host=settings.HOST_NAME,
        announcement_html=settings.ANNOUNCEMENT_HTML or "",
        languages=languages,
        default_catalogs=default_catalogs,
        max_item_rows=MAX_ITEM_ROWS,
        current_year=get_current_year(),
        year_range_defaults=year_range_defaults,
        stored_secret_sentinel=STORED_SECRET_SENTINEL,
        movie_genres=movie_genres_list,
        series_genres=series_genres_list,
        allow_signups=settings.ALLOW_SIGNUPS,
    )
    return HTMLResponse(content=html_content, media_type="text/html")


@app.get("/changelog", response_class=HTMLResponse)
def changelog_page():
    changelog_path = project_root / "CHANGELOG.md"
    if not changelog_path.exists():
        raise HTTPException(status_code=404, detail="No changelog available")
    changelog_html = markdown.markdown(changelog_path.read_text(), extensions=["extra"])
    template = jinja_env.get_template("changelog.html")
    return HTMLResponse(content=template.render(changelog_html=changelog_html, app_version=__version__))


app.include_router(api_router)
