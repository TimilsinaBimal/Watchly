from fastapi import APIRouter
from fastapi.responses import JSONResponse
from loguru import logger

from app.api.models.tokens import TokenRequest, TokenResponse
from app.core.security import redact_token
from app.services.auth import auth_service
from app.services.warmup import warmup_service

router = APIRouter(prefix="/tokens", tags=["Tokens"])


@router.post("/", response_model=TokenResponse)
async def create_token(payload: TokenRequest) -> TokenResponse:
    response, auth_key, user_settings = await auth_service.create_user_token(payload)
    # Warming is a library fetch plus both profile builds, so it runs behind the
    # response. The configure page follows it via GET /{token}/status.
    await warmup_service.mark_pending(response.token)
    warmup_service.enqueue(response.token, auth_key, user_settings)
    logger.info(f"[{redact_token(response.token)}] Token stored, warm-up enqueued")
    return response


@router.post("/identity", status_code=200)
async def check_identity(payload: TokenRequest):
    return await auth_service.get_identity_with_settings(payload)


@router.delete("/", status_code=200)
async def delete_redis_token(payload: TokenRequest):
    await auth_service.delete_user_account(payload)
    return JSONResponse(
        status_code=200,
        content={"status": "ok", "message": "Settings deleted successfully"},
    )
