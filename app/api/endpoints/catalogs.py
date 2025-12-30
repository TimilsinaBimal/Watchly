from fastapi import APIRouter, HTTPException, Response
from loguru import logger

from app.core.security import redact_token
from app.services.recommendation.catalog_service import catalog_service
from app.services.user_cache import user_cache

router = APIRouter()


def _clean_meta(meta: dict) -> dict:
    """Return a sanitized Stremio meta object without internal fields.

    Keeps only public keys and drops internal scoring/IDs/keywords/cast, etc.
    """
    allowed = {
        "id",
        "type",
        "name",
        "poster",
        "background",
        "description",
        "releaseInfo",
        "imdbRating",
        "genres",
        "runtime",
    }
    cleaned = {k: v for k, v in meta.items() if k in allowed}
    # Drop empty values
    cleaned = {k: v for k, v in cleaned.items() if v not in (None, "", [], {}, ())}

    # if id does not start with tt, return None
    if not cleaned.get("id", "").startswith("tt"):
        return None
    return cleaned


@router.get("/{token}/catalog/{type}/{id}.json")
async def get_catalog(type: str, id: str, response: Response, token: str):
    """
    Get catalog recommendations.

    This endpoint delegates all logic to CatalogService facade.
    """
    try:
        # get cached catalog
        cached_data = await user_cache.get_catalog(token, type, id)
        if cached_data:
            return cached_data

        # Delegate to catalog service facade
        recommendations, headers = await catalog_service.get_catalog(token, type, id)

        # Set response headers
        for key, value in headers.items():
            response.headers[key] = value

        # Clean and format metadata
        cleaned = [_clean_meta(m) for m in recommendations]
        cleaned = [m for m in cleaned if m is not None]

        data = {"metas": cleaned}
        # if catalog data is not empty, set the cache
        if cleaned:
            await user_cache.set_catalog(token, type, id, data)
        return data

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"[{redact_token(token)}] Error fetching catalog for {type}/{id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
