from fastapi import APIRouter, HTTPException, Response
from loguru import logger

from app.core.settings import decode_settings
from app.services.catalog_updater import refresh_catalogs_for_credentials
from app.services.recommendation_service import RecommendationService
from app.services.stremio_service import StremioService
from app.utils import redact_token, resolve_user_credentials

router = APIRouter()


@router.get("/catalog/{type}/{id}.json")
@router.get("/{token}/catalog/{type}/{id}.json")
@router.get("/{settings_str}/{token}/catalog/{type}/{id}.json")
async def get_catalog(
    type: str,
    id: str,
    response: Response,
    token: str | None = None,
    settings_str: str | None = None,
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

    logger.info(f"[{redact_token(token)}] Fetching catalog for {type} with id {id}")

    credentials = await resolve_user_credentials(token)

    if type not in ["movie", "series"]:
        logger.warning(f"Invalid type: {type}")
        raise HTTPException(status_code=400, detail="Invalid type. Use 'movie' or 'series'")

    if (
        id not in ["watchly.rec"]
        and not id.startswith("tt")
        and not id.startswith("watchly.genre.")
        and not id.startswith("watchly.loved.")
        and not id.startswith("watchly.watched.")
    ):
        logger.warning(f"Invalid id: {id}")
        raise HTTPException(
            status_code=400,
            detail=(
                "Invalid id. Use 'watchly.rec', 'watchly.loved.<item_id>', 'watchly.watched.<item_id>', or"
                " 'watchly.genre.<genre_id>'"
            ),
        )
    try:
        # Create services with credentials
        stremio_service = StremioService(
            username=credentials.get("username") or "",
            password=credentials.get("password") or "",
            auth_key=credentials.get("authKey"),
        )
        recommendation_service = RecommendationService(stremio_service=stremio_service)

        # Handle item-based recommendations (watchly.loved.tt123456 or watchly.watched.tt123456 or legacy tt123456)
        item_id = None
        if id.startswith("watchly.loved."):
            item_id = id.replace("watchly.loved.", "")
        elif id.startswith("watchly.watched."):
            item_id = id.replace("watchly.watched.", "")
        elif id.startswith("tt"):
            item_id = id

        if item_id:
            recommendations = await recommendation_service.get_recommendations_for_item(item_id=item_id)
            logger.info(f"Found {len(recommendations)} recommendations for {item_id}")
        elif id.startswith("watchly.genre."):
            recommendations = await recommendation_service.get_recommendations_for_genre(genre_id=id, media_type=type)
            logger.info(f"Found {len(recommendations)} recommendations for {id}")
        else:
            # Get recommendations based on library
            # Use settings or config to determine if we should include watched items
            user_settings = decode_settings(settings_str) if settings_str else None
            if user_settings:
                include_watched = user_settings.include_watched
            else:
                include_watched = credentials.get("includeWatched", False)

            # Use last 10 items as sources, get 5 recommendations per source item
            recommendations = await recommendation_service.get_recommendations(
                content_type=type,
                source_items_limit=10,
                recommendations_per_source=5,
                max_results=50,
                include_watched=include_watched,
            )
            logger.info(f"Found {len(recommendations)} recommendations for {type} (includeWatched: {include_watched})")

        logger.info(f"Returning {len(recommendations)} items for {type}")
        # Cache catalog responses for 4 hours (14400 seconds)
        response.headers["Cache-Control"] = "public, max-age=14400"
        return {"metas": recommendations}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[{redact_token(token)}] Error fetching catalog for {type}/{id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{token}/catalog/update")
@router.get("/{settings_str}/{token}/catalog/update")
async def update_catalogs(token: str, settings_str: str | None = None):
    """
    Update the catalogs for the addon. This is a manual endpoint to update the catalogs.
    """
    # Decode credentials from path
    credentials = await resolve_user_credentials(token)

    logger.info(f"[{redact_token(token)}] Updating catalogs in response to manual request")
    updated = await refresh_catalogs_for_credentials(credentials)
    logger.info(f"Manual catalog update completed: {updated}")
    return {"success": updated}
