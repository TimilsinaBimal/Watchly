from fastapi.routing import APIRouter

from app.config import settings

router = APIRouter()


@router.get("/manifest.json")
@router.get("/{token}/manifest.json")
async def manifest(token: str | None = None):
    """Stremio manifest endpoint with optional credential token in the path."""
    # Cache manifest for 1 day (86400 seconds)
    # response.headers["Cache-Control"] = "public, max-age=86400"
    return {
        "id": settings.ADDON_ID,
        "version": "0.1.0",
    "name": settings.ADDON_NAME,
        "description": "Movie and series recommendations based on your Stremio library",
        "logo": "https://raw.githubusercontent.com/TimilsinaBimal/Watchly/refs/heads/main/static/logo.png",
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
        "behaviorHints": {"configurable": True, "configurationRequired": False},
    }
