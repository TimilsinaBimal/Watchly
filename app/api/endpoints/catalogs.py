import re

from fastapi import APIRouter, HTTPException, Response
from loguru import logger

from app.core.security import redact_token
from app.core.settings import UserSettings, get_default_settings
from app.services.catalog_updater import refresh_catalogs_for_credentials
from app.services.recommendation_service import RecommendationService
from app.services.stremio_service import StremioService
from app.services.token_store import token_store

MAX_RESULTS = 50
SOURCE_ITEMS_LIMIT = 10

router = APIRouter()


@router.get("/{token}/catalog/{type}/{id}.json")
async def get_catalog(type: str, id: str, response: Response, token: str):
    if not token:
        raise HTTPException(
            status_code=400,
            detail="Missing credentials token. Please open Watchly from a configured manifest URL.",
        )

    if type not in ["movie", "series"]:
        logger.warning(f"Invalid type: {type}")
        raise HTTPException(status_code=400, detail="Invalid type. Use 'movie' or 'series'")

    # Supported IDs now include dynamic themes and item-based rows
    if id != "watchly.rec" and not any(
        id.startswith(p) for p in ("tt", "watchly.theme.", "watchly.item.", "watchly.loved.", "watchly.watched.")
    ):
        logger.warning(f"Invalid id: {id}")
        raise HTTPException(
            status_code=400,
            detail=(  #
                "Invalid id. Supported: 'watchly.rec', 'watchly.theme.<params>', 'watchly.item.<id>', or"
                " specific item IDs."
            ),
        )

    logger.info(f"[{redact_token(token)}] Fetching catalog for {type} with id {id}")

    credentials = await token_store.get_user_data(token)
    if not credentials:
        raise HTTPException(status_code=401, detail="Invalid or expired token. Please reconfigure the addon.")
    try:
        # Extract settings from credentials
        settings_dict = credentials.get("settings", {})
        user_settings = UserSettings(**settings_dict) if settings_dict else get_default_settings()
        language = user_settings.language if user_settings else "en-US"

        # Create services with credentials
        stremio_service = StremioService(auth_key=credentials.get("authKey"))
        recommendation_service = RecommendationService(
            stremio_service=stremio_service, language=language, user_settings=user_settings
        )

        # Handle item-based recommendations
        if id.startswith("tt"):
            recommendations = await recommendation_service.get_recommendations_for_item(item_id=id)
            logger.info(f"Found {len(recommendations)} recommendations for {id}")

        elif id.startswith("watchly.item.") or id.startswith("watchly.loved.") or id.startswith("watchly.watched."):
            # Extract actual item ID (tt... or tmdb:...)
            item_id = re.sub(r"^watchly\.(item|loved|watched)\.", "", id)
            recommendations = await recommendation_service.get_recommendations_for_item(item_id=item_id)
            logger.info(f"Found {len(recommendations)} recommendations for item {item_id}")

        elif id.startswith("watchly.theme."):
            recommendations = await recommendation_service.get_recommendations_for_theme(
                theme_id=id, content_type=type
            )
            logger.info(f"Found {len(recommendations)} recommendations for theme {id}")

        else:
            recommendations = await recommendation_service.get_recommendations(
                content_type=type, source_items_limit=SOURCE_ITEMS_LIMIT, max_results=MAX_RESULTS
            )
            logger.info(f"Found {len(recommendations)} recommendations for {type}")

        logger.info(f"Returning {len(recommendations)} items for {type}")
        # Cache catalog responses for 4 hours
        response.headers["Cache-Control"] = "public, max-age=14400"
        return {"metas": recommendations}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"[{redact_token(token)}] Error fetching catalog for {type}/{id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{token}/catalog/update")
async def update_catalogs(token: str):
    """
    Update the catalogs for the addon. This is a manual endpoint to update the catalogs.
    """
    # Decode credentials from path
    credentials = await token_store.get_user_data(token)

    logger.info(f"[{redact_token(token)}] Updating catalogs in response to manual request")
    updated = await refresh_catalogs_for_credentials(token, credentials)
    logger.info(f"Manual catalog update completed: {updated}")
    return {"success": updated}
