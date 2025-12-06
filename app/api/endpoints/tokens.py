import httpx
from fastapi import APIRouter, HTTPException, Request
from loguru import logger
from pydantic import BaseModel, Field
from redis import exceptions as redis_exceptions

from app.core.config import settings
from app.core.settings import CatalogConfig, UserSettings, get_default_settings
from app.services.catalog_updater import refresh_catalogs_for_credentials
from app.services.stremio_service import StremioService
from app.services.token_store import token_store
from app.utils import redact_token

router = APIRouter(prefix="/tokens", tags=["tokens"])


class TokenRequest(BaseModel):
    authKey: str | None = Field(default=None, description="Stremio auth key")
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
    stremio_auth_key = payload.authKey.strip() if payload.authKey else None

    if not stremio_auth_key:
        raise HTTPException(status_code=400, detail="Stremio auth key is required.")

    # Remove quotes if present
    if stremio_auth_key.startswith('"') and stremio_auth_key.endswith('"'):
        stremio_auth_key = stremio_auth_key[1:-1].strip()

    rpdb_key = payload.rpdb_key.strip() if payload.rpdb_key else None

    # 1. Fetch user info from Stremio (user_id and email)
    stremio_service = StremioService(auth_key=stremio_auth_key)
    try:
        user_info = await stremio_service.get_user_info()
        user_id = user_info["user_id"]
        email = user_info.get("email", "")
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

    # 4. Prepare payload to store
    payload_to_store = {
        "authKey": stremio_auth_key,
        "email": email,
        "settings": user_settings.model_dump(),
    }

    is_new_account = not existing_data

    # 5. Verify Stremio connection
    verified_auth_key = await _verify_credentials_or_raise({"authKey": stremio_auth_key})

    # 6. Store user data
    try:
        token = await token_store.store_user_data(user_id, payload_to_store)
        logger.info(f"[{redact_token(token)}] Account {'created' if is_new_account else 'updated'} for user {user_id}")
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail="Server configuration error.") from exc
    except (redis_exceptions.RedisError, OSError) as exc:
        raise HTTPException(status_code=503, detail="Storage temporarily unavailable.") from exc

    # 7. Refresh Catalogs
    try:
        await refresh_catalogs_for_credentials(
            payload_to_store, user_settings=user_settings, auth_key=verified_auth_key
        )
    except Exception as exc:
        logger.error(f"Catalog refresh failed: {exc}")
        if is_new_account:
            # Rollback on new account creation failure
            await token_store.delete_token(token)
            raise HTTPException(
                status_code=502,
                detail="Credentials verified, but catalog refresh failed. Please try again.",
            ) from exc

    base_url = settings.HOST_NAME
    manifest_url = f"{base_url}/{token}/manifest.json"
    expires_in = settings.TOKEN_TTL_SECONDS if settings.TOKEN_TTL_SECONDS > 0 else None

    return TokenResponse(
        token=token,
        manifestUrl=manifest_url,
        expiresInSeconds=expires_in,
    )


@router.post("/stremio-identity", status_code=200)
async def check_stremio_identity(payload: TokenRequest):
    """Fetch user info from Stremio and check if account exists."""
    auth_key = payload.authKey.strip() if payload.authKey else None

    if not auth_key:
        raise HTTPException(status_code=400, detail="Auth Key required.")

    if auth_key.startswith('"') and auth_key.endswith('"'):
        auth_key = auth_key[1:-1].strip()

    stremio_service = StremioService(auth_key=auth_key)
    try:
        user_info = await stremio_service.get_user_info()
        user_id = user_info["user_id"]
        email = user_info.get("email", "")
    except Exception as e:
        logger.error(f"Stremio identity check failed: {e}")
        raise HTTPException(
            status_code=400, detail="Failed to verify Stremio identity. Your auth key might be invalid or expired."
        )
    finally:
        await stremio_service.close()

    # Check existence
    try:
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
async def delete_token(payload: TokenRequest):
    """Delete a token based on Stremio auth key."""
    stremio_auth_key = payload.authKey.strip() if payload.authKey else None

    if not stremio_auth_key:
        raise HTTPException(
            status_code=400,
            detail="Stremio auth key is required to delete account.",
        )

    if stremio_auth_key.startswith('"') and stremio_auth_key.endswith('"'):
        stremio_auth_key = stremio_auth_key[1:-1].strip()

    try:
        # Fetch user info from Stremio
        stremio_service = StremioService(auth_key=stremio_auth_key)
        try:
            user_info = await stremio_service.get_user_info()
            user_id = user_info["user_id"]
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to verify Stremio identity: {e}")
        finally:
            await stremio_service.close()

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
