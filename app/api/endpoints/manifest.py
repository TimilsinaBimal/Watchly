from fastapi.routing import APIRouter

from app.services.manifest import manifest_service

router = APIRouter()


@router.get("/manifest.json")
async def manifest():
    manifest = manifest_service.get_base_manifest()
    # since user is not logged in, return empty catalogs
    manifest["catalogs"] = []
    return manifest


@router.get("/{token}/manifest.json")
async def manifest_token(token: str):
    return await manifest_service.get_manifest_for_token(token)
