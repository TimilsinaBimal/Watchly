import re

from fastapi import APIRouter, HTTPException, Response
from loguru import logger

from app.core.security import redact_token
from app.services.recommendation.catalog_service import catalog_service

router = APIRouter()

# Stremio auth tokens are short (~24 char) hex/alphanumeric strings. Accept up
# to 32 chars of [A-Za-z0-9] as a sanity check; anything else is malformed.
_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9]{1,32}$")


@router.get("/{token}/catalog/{type}/{id}.json")
@router.get("/{token}/catalog/{type}/{id}/{extra}.json")
async def get_catalog(response: Response, type: str, id: str, token: str, extra: str | None = None) -> dict:
    if type not in ("movie", "series"):
        raise HTTPException(status_code=400, detail="Invalid content type. Must be 'movie' or 'series'.")

    if not _TOKEN_PATTERN.match(token):
        raise HTTPException(status_code=400, detail="Invalid token.")

    try:
        # Delegate to catalog service facade
        recommendations, headers = await catalog_service.get_catalog(token, type, id)

        # Set response headers
        for key, value in headers.items():
            response.headers[key] = value

        # If recommendations are empty, avoid caching the empty payload aggressively.
        if recommendations is not None and not recommendations.get("metas"):
            response.headers["Cache-Control"] = "no-cache"

        return recommendations

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"[{redact_token(token)}] Error fetching catalog for {type}/{id}: {e}")
        raise HTTPException(status_code=500, detail="Something went wrong. Please try again.")
