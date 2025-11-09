from fastapi import FastAPI, HTTPException, Response

from loguru import logger
from app.services.tmdb_service import TMDBService
from app.services.recommendation_service import RecommendationService
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="Watchly", description="Stremio catalog addon for movie and series recommendations", version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Initialize services
tmdb_service = TMDBService()
recommendation_service = RecommendationService()


@app.get("/manifest.json")
async def manifest(response: Response):
    """Stremio manifest endpoint."""
    # Cache manifest for 1 day (86400 seconds)
    response.headers["Cache-Control"] = "public, max-age=86400"
    return {
        "id": "com.watchly",
        "version": "1.0.0",
        "name": "Watchly",
        "description": "Movie and series recommendations based on your Stremio library",
        "resources": ["catalog"],
        "types": ["movie", "series"],
        "idPrefixes": ["tt"],
        "catalogs": [
            {"type": "movie", "id": "watchly.rec", "name": "Recommended", "extra": []},
            {"type": "series", "id": "watchly.rec", "name": "Recommended", "extra": []},
        ],
    }


@app.get("/catalog/{type}/{id}.json")
async def get_catalog(type: str, id: str, response: Response):
    """
    Stremio catalog endpoint for movies and series.
    Returns recommendations based on user's Stremio library.

    Args:
        type: 'movie' or 'series'
        id: Catalog ID (e.g., 'watchly.rec')
    """
    logger.info(f"Fetching catalog for {type} with id {id}")

    if type not in ["movie", "series"]:
        logger.warning(f"Invalid type: {type}")
        raise HTTPException(status_code=400, detail="Invalid type. Use 'movie' or 'series'")

    if id not in ["watchly.rec"]:
        logger.warning(f"Invalid id: {id}")
        raise HTTPException(status_code=400, detail="Invalid id. Use 'watchly.rec'")

    try:
        # Get recommendations based on library
        # Use last 10 items from library, get 5 recommendations per item
        recommendations = await recommendation_service.get_recommendations(
            content_type=type, seed_limit=10, per_seed_limit=5, max_results=50
        )
        logger.info(f"Found {len(recommendations)} recommendations for {type}")

        # Recommendations already contain full metadata in Stremio format
        # Extract meta from each recommendation
        metas = []
        for rec in recommendations:
            # rec is already the full addon meta response with 'meta' key
            if rec and rec.get("meta"):
                metas.append(rec["meta"])

        logger.info(f"Returning {len(metas)} items for {type}")
        # Cache catalog responses for 1 day (86400 seconds)
        response.headers["Cache-Control"] = "public, max-age=86400"
        return {"metas": metas}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching catalog for {type}/{id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
