from fastapi import APIRouter, HTTPException
from loguru import logger

from app.services.language_service import fetch_languages_list

router = APIRouter()


@router.get("/api/languages")
async def get_languages():
    try:
        languages = await fetch_languages_list()
        return languages
    except Exception as e:
        logger.error(f"Failed to fetch languages: {e}")
        raise HTTPException(status_code=502, detail=f"Failed to fetch languages from TMDB: {e}")
