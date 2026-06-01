from fastapi import APIRouter, HTTPException

from app.services.dashboard import dashboard_service

router = APIRouter(tags=["Dashboard"])


@router.get("/{token}/dashboard/data")
async def dashboard_data(token: str):
    data = await dashboard_service.get_data(token)
    if data is None:
        raise HTTPException(status_code=404, detail="Token not found. Please reconfigure the addon.")
    return data


@router.post("/{token}/dashboard/refresh")
async def dashboard_refresh(token: str):
    if not await dashboard_service.refresh(token):
        raise HTTPException(status_code=404, detail="Token not found. Please reconfigure the addon.")
    return {"status": "started"}
