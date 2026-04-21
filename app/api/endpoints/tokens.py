from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from loguru import logger

from app.api.models.tokens import TokenRequest, TokenResponse
from app.core.security import redact_token
from app.services.auth import auth_service
from app.services.stremio.service import StremioBundle

router = APIRouter(prefix="/tokens", tags=["Tokens"])


async def _trigger_initial_caching(auth_key: str, user_settings, token: str) -> None:
    """Cache library and profiles after token creation. Failures are non-blocking."""
    from app.services.manifest import manifest_service

    bundle = StremioBundle()
    try:
        logger.info(f"[{redact_token(token)}] Caching library and profiles before returning token")
        await manifest_service.cache_library_and_profiles(bundle, auth_key, user_settings, token)
        logger.info(f"[{redact_token(token)}] Successfully cached library and profiles")
    except Exception as e:
        logger.warning(
            f"[{redact_token(token)}] Failed to cache library and profiles: {e}. "
            "Continuing anyway - will cache on manifest request."
        )
    finally:
        await bundle.close()


@router.post("/", response_model=TokenResponse)
async def create_token(payload: TokenRequest) -> TokenResponse:
    try:
        response, auth_key, user_settings = await auth_service.create_user_token(payload)
        await _trigger_initial_caching(auth_key, user_settings, response.token)
        return response
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
