from fastapi import APIRouter, HTTPException
from loguru import logger

from app.utils import clear_cache

router = APIRouter(prefix="/cache")


@router.delete("/")
async def clear_caches():
    """
    Clear all server-side caches (API responses and function results).
    This will force fresh data to be fetched from external APIs on next request.
    """
    try:
        clear_cache()
        logger.info("Cache cleared via API endpoint")
        return {"message": "All caches cleared successfully", "status": "success"}
    except Exception as e:
        logger.error(f"Error clearing cache: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to clear cache: {str(e)}")
