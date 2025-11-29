from fastapi import APIRouter, HTTPException
from loguru import logger

from app.services.tmdb_service import TMDBService

router = APIRouter()


@router.get("/api/languages")
async def get_languages():
    """
    Proxy endpoint to fetch languages from TMDB.
    """
    tmdb_service = TMDBService()
    try:
        languages = await tmdb_service._make_request("/configuration/languages")
        if not languages:
            return []
        return languages
    except Exception as e:
        logger.error(f"Failed to fetch languages: {e}")
        raise HTTPException(status_code=502, detail="Failed to fetch languages from TMDB")
    finally:
        await tmdb_service.close()
