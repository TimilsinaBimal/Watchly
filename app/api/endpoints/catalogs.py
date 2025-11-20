from fastapi import APIRouter, HTTPException, Response
from loguru import logger
from app.services.recommendation_service import RecommendationService
from app.services.stremio_service import StremioService
from app.utils import decode_credentials
from app.services.catalog import DynamicCatalogService

router = APIRouter()


@router.get("/catalog/{type}/{id}.json")
@router.get("/{encoded}/catalog/{type}/{id}.json")
async def get_catalog(
    encoded: str,
    type: str,
    id: str,
    response: Response,
):
    """
    Stremio catalog endpoint for movies and series.
    Returns recommendations based on user's Stremio library.

    Args:
        encoded: Base64 encoded credentials
        type: 'movie' or 'series'
        id: Catalog ID (e.g., 'watchly.rec')
    """
    logger.info(f"Fetching catalog for {type} with id {id}")

    # Decode credentials from path
    credentials = decode_credentials(encoded)

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
        stremio_service = StremioService(username=credentials['username'], password=credentials['password'])
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


@router.get("/{encoded}/catalog/update")
async def update_catalogs(encoded: str):
    """
    Update the catalogs for the addon. This is a manual endpoint to update the catalogs.
    """
    # Decode credentials from path
    credentials = decode_credentials(encoded)

    stremio_service = StremioService(username=credentials['username'], password=credentials['password'])
    library_items = await stremio_service.get_library_items()
    dynamic_catalog_service = DynamicCatalogService(stremio_service=stremio_service)
    catalogs = await dynamic_catalog_service.get_watched_loved_catalogs(library_items=library_items)
    genre_based_catalogs = await dynamic_catalog_service.get_genre_based_catalogs(library_items=library_items)
    catalogs += genre_based_catalogs
    # update catalogs

    logger.info(f"Updating Catalogs: {catalogs}")
    auth_key = await stremio_service._get_auth_token()
    updated = await stremio_service.update_catalogs(catalogs, auth_key)
    logger.info(f"Updated catalogs: {updated}")
    return {"success": updated}
