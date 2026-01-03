from fastapi import APIRouter, HTTPException, Response
from loguru import logger

from app.core.security import redact_token
from app.services.recommendation.catalog_service import catalog_service

router = APIRouter()


@router.get("/{token}/catalog/{type}/{id}.json")
@router.get("/{token}/catalog/{type}/{id}/{extra}.json")
async def get_catalog(response: Response, type: str, id: str, token: str, extra: str | None = None):
    """
    Get catalog recommendations.

    This endpoint delegates all logic to CatalogService facade.
    """
    try:
        # Delegate to catalog service facade
        recommendations, headers = await catalog_service.get_catalog(token, type, id)

        # Set response headers
        for key, value in headers.items():
            response.headers[key] = value

        return recommendations

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"[{redact_token(token)}] Error fetching catalog for {type}/{id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
