from fastapi import APIRouter, HTTPException, Response
from loguru import logger
from app.services.recommendation_service import RecommendationService
from app.services.stremio_service import StremioService
from app.services.catalog_updater import refresh_catalogs_for_credentials
from app.utils import resolve_user_credentials

router = APIRouter()


@router.get("/catalog/{type}/{id}.json")
@router.get("/{token}/catalog/{type}/{id}.json")
async def get_catalog(
    token: str | None,
    type: str,
    id: str,
    response: Response,
):
    """
    Stremio catalog endpoint for movies and series.
    Returns recommendations based on user's Stremio library.

    Args:
    token: Redis-backed credential token
        type: 'movie' or 'series'
        id: Catalog ID (e.g., 'watchly.rec')
    """
    if not token:
        raise HTTPException(
            status_code=400,
            detail="Missing credentials token. Please open Watchly from a configured manifest URL.",
        )

    logger.info(f"Fetching catalog for {type} with id {id}")

    credentials = await resolve_user_credentials(token)

    if type not in ["movie", "series"]:
        logger.warning(f"Invalid type: {type}")
        raise HTTPException(
            status_code=400, detail="Invalid type. Use 'movie' or 'series'"
        )

    if id not in ["watchly.rec"] and not id.startswith("tt") and not id.startswith("watchly.genre."):
        logger.warning(f"Invalid id: {id}")
        raise HTTPException(
            status_code=400, detail="Invalid id. Use 'watchly.rec' or 'watchly.genre.<genre_id>'"
        )
    try:
        # Create services with credentials
        stremio_service = StremioService(
            username=credentials.get('username') or "",
            password=credentials.get('password') or "",
            auth_key=credentials.get('authKey'),
        )
        recommendation_service = RecommendationService(stremio_service=stremio_service)

        # if id starts with tt, then return recommendations for that particular item
        if id.startswith("tt"):
            recommendations = await recommendation_service.get_recommendations_for_item(item_id=id)
            logger.info(f"Found {len(recommendations)} recommendations for {id}")
        elif id.startswith("watchly.genre."):
            recommendations = await recommendation_service.get_recommendations_for_genre(
                genre_id=id, media_type=type
            )
            logger.info(f"Found {len(recommendations)} recommendations for {id}")
        else:
            # Get recommendations based on library
            # Use config to determine if we should include watched items
            include_watched = credentials.get('includeWatched', False)
            # Use last 10 items as sources, get 5 recommendations per source item
            recommendations = await recommendation_service.get_recommendations(
                content_type=type,
                source_items_limit=10,
                recommendations_per_source=5,
                max_results=50,
                include_watched=include_watched
            )
            logger.info(f"Found {len(recommendations)} recommendations for {type} (includeWatched: {include_watched})")

        logger.info(f"Returning {len(recommendations)} items for {type}")
        # Cache catalog responses for 4 hours (14400 seconds)
        response.headers["Cache-Control"] = "public, max-age=14400"
        return {"metas": recommendations}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching catalog for {type}/{id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{token}/catalog/update")
async def update_catalogs(token: str):
    """
    Update the catalogs for the addon. This is a manual endpoint to update the catalogs.
    """
    # Decode credentials from path
    credentials = await resolve_user_credentials(token)

    logger.info("Updating catalogs in response to manual request")
    updated = await refresh_catalogs_for_credentials(credentials)
    logger.info(f"Manual catalog update completed: {updated}")
    return {"success": updated}
