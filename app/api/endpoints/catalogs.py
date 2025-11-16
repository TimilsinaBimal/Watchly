from fastapi import APIRouter, HTTPException, Response
from loguru import logger
from app.services.recommendation_service import RecommendationService
from app.services.stremio_service import StremioService

router = APIRouter(prefix="/catalog")

recommendation_service = RecommendationService()


@router.get("/{type}/{id}.json")
async def get_catalog(
    type: str,
    id: str,
    response: Response,
):
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
        raise HTTPException(
            status_code=400, detail="Invalid type. Use 'movie' or 'series'"
        )

    if id not in ["watchly.rec"] and not id.startswith("tt"):
        logger.warning(f"Invalid id: {id}")
        raise HTTPException(status_code=400, detail="Invalid id. Use 'watchly.rec'")
    try:
        # if id starts with tt, then return recommendations for that particular item
        if id.startswith("tt"):
            recommendations = await recommendation_service.get_recommendations_for_item(item_id=id)
            logger.info(f"Found {len(recommendations)} recommendations for {id}")
        else:
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


@router.get("/update")
async def update_catalogs():
    """
    Update the catalogs for the addon. This is a manual endpoint to update the catalogs.
    """
    stremio_service = StremioService()
    library_items = await stremio_service.get_library_items()
    seen_items = set()
    catalogs = []
    seed = {
        "watched": {
            "movie": False,
            "series": False,
        },
        "loved": {
            "movie": False,
            "series": False,
        },
    }
    # checked loved items
    loved_items = library_items.get("loved", [])
    watched_items = library_items.get("watched", [])
    # now find first few items
    for l_item in loved_items:
        print(l_item)
        type_ = l_item.get("type")
        if type_ in ["tv"]:
            type_ = "series"
        if l_item.get("_id") in seen_items or seed["loved"][type_]:
            continue
        seen_items.add(l_item.get("_id"))
        seed["loved"][type_] = True
        catalogs.append(
            {
                "type": type_,
                "id": l_item.get("_id"),
                "name": f"Because you Loved {l_item.get('name')}",
                "extra": [],
            }
        )
    for w_item in watched_items:
        type_ = l_item.get("type")
        if type_ in ["tv"]:
            type_ = "series"

        if w_item.get("_id") in seen_items or seed["watched"][type_]:
            continue
        seen_items.add(w_item.get("_id"))
        seed["watched"][type_] = True
        catalogs.append(
            {
                "type": type_,
                "id": w_item.get("_id"),
                "name": f"Because you Watched {w_item.get('name')}",
                "extra": [],
            }
        )
    # update catalogs
    auth_key = await stremio_service._get_auth_token()
    updated = await stremio_service.update_catalogs(catalogs, auth_key)
    logger.info(f"Updated catalogs: {updated}")
    return {"success": updated}
