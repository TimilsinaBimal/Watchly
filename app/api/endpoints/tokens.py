from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from loguru import logger

from app.api.models.tokens import TokenRequest, TokenResponse
from app.services.auth import auth_service

router = APIRouter(prefix="/tokens", tags=["Tokens"])


@router.post("/", response_model=TokenResponse)
async def create_token(payload: TokenRequest) -> TokenResponse:
    try:
        return await auth_service.create_user_token(payload)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(f"Token creation failed: {exc}")
        raise HTTPException(status_code=503, detail="Storage temporarily unavailable.")


@router.post("/stremio-identity", status_code=200)
async def check_stremio_identity(payload: TokenRequest):
    try:
        return await auth_service.get_identity_with_settings(payload)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(f"Identity check failed: {exc}")
        raise HTTPException(status_code=503, detail="Service temporarily unavailable.")


@router.delete("/", status_code=200)
async def delete_redis_token(payload: TokenRequest):
    try:
        await auth_service.delete_user_account(payload)
        return JSONResponse(status_code=200, content="Settings deleted successfully")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(f"Account deletion failed: {exc}")
        raise HTTPException(status_code=503, detail="Service temporarily unavailable.")
