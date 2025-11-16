from fastapi import APIRouter
from .endpoints.manifest import router as manifest_router
from .endpoints.catalogs import router as catalogs_router
from .endpoints.caching import router as caching_router

api_router = APIRouter()


@api_router.get("/")
async def root():
    return {"message": "Watchly API is running"}


api_router.include_router(manifest_router)
api_router.include_router(catalogs_router)
api_router.include_router(caching_router)
