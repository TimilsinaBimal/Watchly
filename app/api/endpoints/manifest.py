from fastapi.routing import APIRouter
from fastapi import Response

router = APIRouter()


@router.get("/manifest.json")
async def manifest(response: Response):
    """Stremio manifest endpoint."""
    # Cache manifest for 1 day (86400 seconds)
    response.headers["Cache-Control"] = "public, max-age=86400"
    return {
        "id": "com.bimal.watchly",
        "version": "0.1.0",
        "name": "Watchly",
        "description": "Movie and series recommendations based on your Stremio library",
        "resources": ["catalog", "stream"],
        "types": ["movie", "series"],
        "idPrefixes": ["tt"],
        "catalogs": [
            {"type": "movie", "id": "watchly.rec", "name": "Recommended", "extra": []},
            {"type": "series", "id": "watchly.rec", "name": "Recommended", "extra": []},
        ],
    }
