import httpx
from fastapi import APIRouter, HTTPException, Request
from loguru import logger
from pydantic import BaseModel, Field
from redis import exceptions as redis_exceptions

from app.core.config import settings
from app.core.security import redact_token
from app.core.settings import CatalogConfig, UserSettings, get_default_settings
from app.services.stremio_service import StremioService
from app.services.token_store import token_store

router = APIRouter(prefix="/tokens", tags=["tokens"])


class TokenRequest(BaseModel):
    authKey: str | None = Field(default=None, description="Stremio auth key")
    email: str | None = Field(default=None, description="Stremio account email")
    password: str | None = Field(default=None, description="Stremio account password (stored securely)")
    catalogs: list[CatalogConfig] | None = Field(default=None, description="Optional catalog configuration")
    language: str = Field(default="en-US", description="Language for TMDB API")
    rpdb_key: str | None = Field(default=None, description="Optional RPDB API Key")
    excluded_movie_genres: list[str] = Field(default_factory=list, description="List of movie genre IDs to exclude")
    excluded_series_genres: list[str] = Field(default_factory=list, description="List of series genre IDs to exclude")


class TokenResponse(BaseModel):
    token: str
    manifestUrl: str
    expiresInSeconds: int | None = Field(
        default=None,
        description="Number of seconds before the token expires (None means it does not expire)",
    )


async def _verify_credentials_or_raise(payload: dict) -> str:
    """Ensure the supplied credentials/auth key are valid before issuing tokens."""
    stremio_service = StremioService(auth_key=payload.get("authKey"))

    try:
        if payload.get("authKey"):
            await stremio_service.get_addons(auth_key=payload["authKey"])
            return payload["authKey"]
        raise ValueError("Please Login using stremio account to continue!")
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc) or "Invalid Stremio credentials or auth key.",
        ) from exc
    except httpx.HTTPStatusError as exc:  # pragma: no cover - depends on remote API
        status_code = exc.response.status_code
        logger.warning("Credential validation failed with status %s", status_code)
        if status_code in {401, 403}:
            raise HTTPException(
                status_code=400,
                detail="Invalid Stremio credentials or auth key. Please double-check and try again.",
            ) from exc
        raise HTTPException(
            status_code=502,
            detail="Stremio returned an unexpected response. Please try again shortly.",
        ) from exc
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Unexpected error while validating credentials: {}", exc, exc_info=True)
        raise HTTPException(
            status_code=502,
            detail="Unable to reach Stremio right now. Please try again later.",
        ) from exc
    finally:
        await stremio_service.close()


@router.post("/", response_model=TokenResponse)
async def create_token(payload: TokenRequest, request: Request) -> TokenResponse:
    # Prefer email+password if provided; else require authKey
    email = (payload.email or "").strip() or None
    password = (payload.password or "").strip() or None
    stremio_auth_key = (payload.authKey or "").strip() or None

    if not (email and password) and not stremio_auth_key:
        raise HTTPException(status_code=400, detail="Provide email+password or a valid Stremio auth key.")

    # Remove quotes if present for authKey
    if stremio_auth_key and stremio_auth_key.startswith('"') and stremio_auth_key.endswith('"'):
        stremio_auth_key = stremio_auth_key[1:-1].strip()

    rpdb_key = payload.rpdb_key.strip() if payload.rpdb_key else None

    # 1. Establish a valid auth key and fetch user info
    if email and password:
        stremio_service = StremioService(username=email, password=password)
        try:
            # Centralized key retrieval (validates/refreshes)
            stremio_auth_key = await stremio_service.get_auth_key()
            user_info = await stremio_service.get_user_info(stremio_auth_key)
            user_id = user_info["user_id"]
            resolved_email = user_info.get("email", email)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to verify Stremio identity: {e}")
        finally:
            await stremio_service.close()
    else:
        stremio_service = StremioService(auth_key=stremio_auth_key)
        try:
            user_info = await stremio_service.get_user_info(stremio_auth_key)
            user_id = user_info["user_id"]
            resolved_email = user_info.get("email", "")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to verify Stremio identity: {e}")
        finally:
            await stremio_service.close()

    # 2. Check if user already exists
    token = token_store.get_token_from_user_id(user_id)
    existing_data = await token_store.get_user_data(token)

    # 3. Construct Settings
    default_settings = get_default_settings()

    user_settings = UserSettings(
        language=payload.language or default_settings.language,
        catalogs=payload.catalogs if payload.catalogs else default_settings.catalogs,
        rpdb_key=rpdb_key,
        excluded_movie_genres=payload.excluded_movie_genres,
        excluded_series_genres=payload.excluded_series_genres,
    )

    is_new_account = not existing_data

    # 4. Verify Stremio connection
    # Already verified above. For authKey path, still validate to catch expired keys
    if not (email and password):
        verified_auth_key = await _verify_credentials_or_raise({"authKey": stremio_auth_key})
    else:
        verified_auth_key = stremio_auth_key

    # 5. Prepare payload to store
    payload_to_store = {
        "authKey": verified_auth_key,
        "email": resolved_email or email or "",
        "settings": user_settings.model_dump(),
    }
    # Store password if provided so we can refresh authKey later without user action
    if email and password:
        payload_to_store["password"] = password

    # 6. Store user data
    try:
        token = await token_store.store_user_data(user_id, payload_to_store)
        logger.info(
            "[%s] Account %s for user %s",
            redact_token(token),
            "created" if is_new_account else "updated",
            user_id,
        )
    except RuntimeError as exc:
        # Surface a clear message when secure storage fails
        if "PASSWORD_ENCRYPT_FAILED" in str(exc):
            raise HTTPException(status_code=500, detail="Secure storage failed. Please log in again.") from exc
        raise HTTPException(status_code=500, detail="Server configuration error.") from exc
    except (redis_exceptions.RedisError, OSError) as exc:
        raise HTTPException(status_code=503, detail="Storage temporarily unavailable.") from exc

    base_url = settings.HOST_NAME
    manifest_url = f"{base_url}/{token}/manifest.json"
    expires_in = settings.TOKEN_TTL_SECONDS if settings.TOKEN_TTL_SECONDS > 0 else None

    return TokenResponse(
        token=token,
        manifestUrl=manifest_url,
        expiresInSeconds=expires_in,
    )


async def get_stremio_user_data(payload: TokenRequest) -> tuple[str, str]:
    email = (payload.email or "").strip() or None
    password = (payload.password or "").strip() or None
    auth_key = (payload.authKey or "").strip() or None

    if email and password:
        svc = StremioService(username=email, password=password)
        try:
            auth_key = await svc.get_auth_key()
            user_info = await svc.get_user_info(auth_key)
            return user_info["user_id"], user_info.get("email", email)
        except Exception as e:
            logger.error(f"Stremio identity check failed (email/password): {e}")
            raise HTTPException(
                status_code=400,
                detail="Failed to verify Stremio identity with email/password.",
            )
        finally:
            await svc.close()
    elif auth_key:
        if auth_key.startswith('"') and auth_key.endswith('"'):
            auth_key = auth_key[1:-1].strip()
        svc = StremioService(auth_key=auth_key)
        try:
            user_info = await svc.get_user_info(auth_key)
            return user_info["user_id"], user_info.get("email", "")
        except Exception as e:
            logger.error(f"Stremio identity check failed: {e}")
            raise HTTPException(
                status_code=400,
                detail="Failed to verify Stremio identity. Your auth key might be invalid or expired.",
            )
        finally:
            await svc.close()
    else:
        raise HTTPException(status_code=400, detail="Provide email+password or auth key.")


@router.post("/stremio-identity", status_code=200)
async def check_stremio_identity(payload: TokenRequest):
    """Fetch user info from Stremio and check if account exists."""
    user_id, email = await get_stremio_user_data(payload)
    try:
        # Check existence
        token = token_store.get_token_from_user_id(user_id)
        user_data = await token_store.get_user_data(token)
        exists = bool(user_data)
    except ValueError:
        exists = False
        user_data = None

    response = {"user_id": user_id, "email": email, "exists": exists}
    if exists and user_data:
        response["settings"] = user_data.get("settings")

    return response


@router.delete("/", status_code=200)
async def delete_redis_token(payload: TokenRequest):
    """Delete a token based on Stremio auth key."""
    try:
        user_id, _ = await get_stremio_user_data(payload)

        # Get token from user_id
        token = token_store.get_token_from_user_id(user_id)

        # Verify account exists
        existing_data = await token_store.get_user_data(token)
        if not existing_data:
            raise HTTPException(status_code=404, detail="Account not found.")

        # Delete the token
        await token_store.delete_token(token)
        logger.info(f"[{redact_token(token)}] Token deleted for user {user_id}")
        return {"detail": "Settings deleted successfully"}
    except HTTPException:
        raise
    except (redis_exceptions.RedisError, OSError) as exc:
        logger.error("Token deletion failed: {}", exc)
        raise HTTPException(
            status_code=503,
            detail="Token deletion is temporarily unavailable. Please try again once Redis is reachable.",
        ) from exc
