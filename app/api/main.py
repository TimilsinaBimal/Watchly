from fastapi import APIRouter
from .endpoints.manifest import router as manifest_router
from .endpoints.catalogs import router as catalogs_router
from .endpoints.caching import router as caching_router
from .endpoints.streams import router as streams_router
from .endpoints.tokens import router as tokens_router
from .endpoints.health import router as health_router

api_router = APIRouter()


@api_router.get("/")
async def root():
    return {"message": "Watchly API is running"}


api_router.include_router(manifest_router)
api_router.include_router(catalogs_router)
api_router.include_router(caching_router)
api_router.include_router(streams_router)
api_router.include_router(tokens_router)
api_router.include_router(health_router)
