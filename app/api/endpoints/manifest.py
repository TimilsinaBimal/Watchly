from fastapi.routing import APIRouter

from app.config import settings

router = APIRouter()


@router.get("/manifest.json")
@router.get("/{encoded}/manifest.json")
async def manifest(encoded: str):
    """Stremio manifest endpoint with encoded credentials in path."""
    # Cache manifest for 1 day (86400 seconds)
    # response.headers["Cache-Control"] = "public, max-age=86400"
    return {
        "id": settings.ADDON_ID,
        "version": "0.1.0",
        "name": "Watchly",
        "description": "Movie and series recommendations based on your Stremio library",
        "resources": [
            {"name": "catalog", "types": ["movie", "series"], "idPrefixes": ["tt"]},
            {"name": "stream", "types": ["movie", "series"], "idPrefixes": ["tt"]},
        ],
        "types": ["movie", "series"],
        "idPrefixes": ["tt"],
        "catalogs": [
            {"type": "movie", "id": "watchly.rec", "name": "Recommended", "extra": []},
            {"type": "series", "id": "watchly.rec", "name": "Recommended", "extra": []},
        ],
        "behaviorHints": {"configurable": True, "configurationRequired": True},
    }
