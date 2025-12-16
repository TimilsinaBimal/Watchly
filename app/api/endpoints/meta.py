from async_lru import alru_cache
from fastapi import APIRouter, HTTPException
from httpx import AsyncClient, HTTPStatusError
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


@router.get("rpdb/validation")
async def validate_rpdb_key(api_key: str) -> bool:
    base_url = f"https://api.ratingposterdb.com/{api_key}/imdb/poster-default/tt22202452.jpg?fallback=true"  # pluribus

    async with AsyncClient(timeout=10) as client:
        try:
            req = await client.get(base_url)
            req.raise_for_status()
            return True
        except HTTPStatusError as e:
            logger.warning(f"Invalid API Key: {e}")
        except Exception as e:
            logger.error(f"Unexpected error while validations rpdb key: {e}")
        return False


# @router.get("/top-posters/validate")
# async def validate_top_posters_key(api_key: str):
