from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health", summary="Simple readiness probe")
async def health_check() -> dict:
    return {"status": "healthy"}
