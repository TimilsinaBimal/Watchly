from async_lru import alru_cache
from fastapi import Response
from fastapi.routing import APIRouter

from app.core.config import settings
from app.services.catalog import DynamicCatalogService
from app.services.stremio_service import StremioService
from app.utils import resolve_user_credentials

router = APIRouter()


def get_base_manifest():
    return {
        "id": settings.ADDON_ID,
        "version": settings.APP_VERSION,
        "name": settings.ADDON_NAME,
        "description": "Movie and series recommendations based on your Stremio library",
        "logo": "https://raw.githubusercontent.com/TimilsinaBimal/Watchly/refs/heads/main/static/logo.png",
        "resources": [{"name": "catalog", "types": ["movie", "series"], "idPrefixes": ["tt"]}],
        "types": ["movie", "series"],
        "idPrefixes": ["tt"],
        "catalogs": [
            {"type": "movie", "id": "watchly.rec", "name": "Recommended", "extra": []},
            {"type": "series", "id": "watchly.rec", "name": "Recommended", "extra": []},
        ],
        "behaviorHints": {"configurable": True, "configurationRequired": False},
    }


# Cache catalog definitions for 1 hour (3600s)
@alru_cache(maxsize=1000, ttl=3600)
async def fetch_catalogs(token: str | None = None):
    if not token:
        return []

    credentials = await resolve_user_credentials(token)
    stremio_service = StremioService(
        username=credentials.get("username") or "",
        password=credentials.get("password") or "",
        auth_key=credentials.get("authKey"),
    )
    # Note: get_library_items is expensive, but we need it to determine *which* genre catalogs to show.
    library_items = await stremio_service.get_library_items()
    dynamic_catalog_service = DynamicCatalogService(stremio_service=stremio_service)

    # Base catalogs are already in manifest, these are *extra* dynamic ones
    catalogs = await dynamic_catalog_service.get_watched_loved_catalogs(library_items=library_items)
    catalogs += await dynamic_catalog_service.get_genre_based_catalogs(library_items=library_items)

    return catalogs


@router.get("/manifest.json")
@router.get("/{token}/manifest.json")
async def manifest(response: Response, token: str | None = None):
    """Stremio manifest endpoint with optional credential token in the path."""
    # Cache manifest for 1 day (86400 seconds)
    response.headers["Cache-Control"] = "public, max-age=86400"

    base_manifest = get_base_manifest()
    if token:
        catalogs = await fetch_catalogs(token)
        if catalogs:
            # Append dynamic catalogs to the base ones
            base_manifest["catalogs"] += catalogs
    return base_manifest
