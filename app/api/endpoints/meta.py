from async_lru import alru_cache
from fastapi import APIRouter, HTTPException
from loguru import logger

from app.services.tmdb_service import get_tmdb_service

router = APIRouter()


@alru_cache(maxsize=1, ttl=24 * 60 * 60)
async def _cached_languages():
    tmdb = get_tmdb_service()
    return await tmdb._make_request("/configuration/languages")


@router.get("/api/languages")
async def get_languages():
    """
    Proxy endpoint to fetch languages from TMDB.
    """
    try:
        languages = await _cached_languages()
        if not languages:
            return []
        return languages
    except Exception as e:
        logger.error(f"Failed to fetch languages: {e}")
        raise HTTPException(status_code=502, detail="Failed to fetch languages from TMDB")
    finally:
        # shared client: no explicit close
        pass
