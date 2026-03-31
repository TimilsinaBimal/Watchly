from fastapi import APIRouter, HTTPException, Query
from loguru import logger

from app.services.language_service import fetch_languages_list
from app.services.tmdb.service import get_tmdb_service

router = APIRouter()


@router.get("/api/languages")
async def get_languages():
    try:
        languages = await fetch_languages_list()
        return languages
    except Exception as e:
        logger.error(f"Failed to fetch languages: {e}")
        raise HTTPException(status_code=502, detail=f"Failed to fetch languages from TMDB: {e}")


@router.get("/api/meta/images")
async def get_meta_images(
    media_type: str = Query(..., description="movie or tv"),
    tmdb_id: int = Query(..., description="TMDB ID"),
    language: str = Query("en-US", description="Language preference (e.g. en-US, fr-FR)"),
):
    """Fetch language-aware poster, logo, and background images for a title."""
    try:
        tmdb_service = get_tmdb_service(language=language)
        images = await tmdb_service.get_images_for_title(media_type, tmdb_id, language=language)
        return images
    except Exception as e:
        logger.error(f"Failed to fetch images for {media_type}/{tmdb_id}: {e}")
        raise HTTPException(status_code=502, detail=f"Failed to fetch images from TMDB: {e}")
