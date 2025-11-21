from fastapi import APIRouter

from app.config import settings

router = APIRouter(prefix="/announcement", tags=["announcement"])


@router.get("/")
async def get_announcement() -> dict:
    return {"html": settings.ANNOUNCEMENT_HTML or ""}
