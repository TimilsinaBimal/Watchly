from fastapi import APIRouter
from loguru import logger

from app.services.token_store import token_store

router = APIRouter()


@router.get("/stats")
async def get_stats() -> dict:
    """Return lightweight public stats for the homepage.

    Total users is cached for 12 hours inside TokenStore to avoid heavy scans.
    """
    try:
        total = await token_store.count_users()
    except Exception as exc:
        logger.warning(f"Failed to get total users: {exc}")
        total = 0
    return {"total_users": total}
