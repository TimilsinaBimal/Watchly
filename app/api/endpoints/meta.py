from fastapi import APIRouter, HTTPException
from loguru import logger

from app.services.tmdb_service import get_tmdb_service

router = APIRouter()


@router.get("/api/languages")
async def get_languages():
    """
    Proxy endpoint to fetch languages from TMDB.
    """
    try:
        tmdb = get_tmdb_service()
        languages = await tmdb._make_request("/configuration/languages")
        if not languages:
            return []
        return languages
    except Exception as e:
        logger.error(f"Failed to fetch languages: {e}")
        raise HTTPException(status_code=502, detail="Failed to fetch languages from TMDB")
    finally:
        # shared client: no explicit close
        pass
