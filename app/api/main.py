from fastapi import APIRouter

from .endpoints.announcement import router as announcement_router
from .endpoints.catalogs import router as catalogs_router
from .endpoints.health import router as health_router
from .endpoints.manifest import router as manifest_router
from .endpoints.meta import router as meta_router
from .endpoints.poster_rating import router as poster_rating_router
from .endpoints.stats import router as stats_router
from .endpoints.tokens import router as tokens_router

api_router = APIRouter()


@api_router.get("/")
async def root():
    return {"message": "Watchly API is running"}


api_router.include_router(manifest_router)
api_router.include_router(catalogs_router)
api_router.include_router(tokens_router)
api_router.include_router(health_router)
api_router.include_router(meta_router)
api_router.include_router(announcement_router)
api_router.include_router(stats_router)
api_router.include_router(poster_rating_router)
