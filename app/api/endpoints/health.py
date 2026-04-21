from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter(tags=["health"])


@router.get("/health", summary="Simple readiness probe")
async def health_check() -> JSONResponse:
    return JSONResponse(status_code=200, content="System healthy!")
