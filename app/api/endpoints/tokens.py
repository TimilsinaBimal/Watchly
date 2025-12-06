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
    watchly_username: str | None = Field(default=None, description="Watchly account (user/id)")
    watchly_password: str | None = Field(default=None, description="Watchly account password")
    username: str | None = Field(default=None, description="Stremio username or email")
    password: str | None = Field(default=None, description="Stremio password")
    authKey: str | None = Field(default=None, description="Existing Stremio auth key")
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
    stremio_service = StremioService(
        username=payload.get("username") or "",
        password=payload.get("password") or "",
        auth_key=payload.get("authKey"),
    )

    try:
        if payload.get("authKey") and not payload.get("username"):
            await stremio_service.get_addons(auth_key=payload["authKey"])
            return payload["authKey"]
        auth_key = await stremio_service.get_auth_key()
        return auth_key
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
    # Stremio Credentials
    stremio_username = payload.username.strip() if payload.username else None
    stremio_password = payload.password
    stremio_auth_key = payload.authKey.strip() if payload.authKey else None

    # Watchly Credentials (The new flow)
    watchly_username = payload.watchly_username.strip() if payload.watchly_username else None
    watchly_password = payload.watchly_password

    rpdb_key = payload.rpdb_key.strip() if payload.rpdb_key else None

    if stremio_auth_key and stremio_auth_key.startswith('"') and stremio_auth_key.endswith('"'):
        stremio_auth_key = stremio_auth_key[1:-1].strip()

    # Construct Settings
    default_settings = get_default_settings()

    user_settings = UserSettings(
        language=payload.language or default_settings.language,
        catalogs=payload.catalogs if payload.catalogs else default_settings.catalogs,
        rpdb_key=rpdb_key,
        excluded_movie_genres=payload.excluded_movie_genres,
        excluded_series_genres=payload.excluded_series_genres,
    )

    # Logic to handle "Update Mode" (Watchly credentials only)
    is_update_mode = (watchly_username and watchly_password) and not (
        stremio_username or stremio_password or stremio_auth_key
    )

    if is_update_mode:
        # User is trying to update settings using only Watchly credentials
        # We must retrieve their existing Stremio credentials from the store
        temp_payload_for_derivation = {
            "watchly_username": watchly_username,
            "watchly_password": watchly_password,
            "username": None,
            "password": None,
            "authKey": None,
        }
        derived_token = token_store.derive_token(temp_payload_for_derivation)
        existing_data = await token_store.get_payload(derived_token)

        if not existing_data:
            raise HTTPException(
                status_code=404,
                detail="Account not found. Please start as a New User to connect Stremio.",
            )

        # Hydrate Stremio credentials from existing data
        stremio_username = existing_data.get("username")
        stremio_password = existing_data.get("password")
        stremio_auth_key = existing_data.get("authKey")

    # Regular Validation Logic
    if stremio_username and not stremio_password:
        raise HTTPException(status_code=400, detail="Stremio password is required when username is provided.")

    if stremio_password and not stremio_username:
        raise HTTPException(
            status_code=400,
            detail="Stremio username/email is required when password is provided.",
        )

    if not stremio_auth_key and not (stremio_username and stremio_password):
        raise HTTPException(
            status_code=400,
            detail="Provide either a Stremio auth key or both Stremio username and password.",
        )

    # Payload to store includes BOTH Watchly and Stremio credentials + User Settings
    payload_to_store = {
        "watchly_username": watchly_username,
        "watchly_password": watchly_password,
        "username": stremio_username,
        "password": stremio_password,
        "authKey": stremio_auth_key,
        "settings": user_settings.model_dump(),
    }

    verified_auth_key = await _verify_credentials_or_raise(payload_to_store)

    try:
        token, created = await token_store.store_payload(payload_to_store)
        logger.info(f"[{redact_token(token)}] Token {'created' if created else 'updated'}")
    except RuntimeError as exc:
        logger.error("Token storage failed: {}", exc)
        raise HTTPException(
            status_code=500,
            detail="Server configuration error: TOKEN_SALT must be set to a secure value.",
        ) from exc
    except (redis_exceptions.RedisError, OSError) as exc:
        logger.error("Token storage unavailable: {}", exc)
        raise HTTPException(
            status_code=503,
            detail="Token storage is temporarily unavailable. Please try again once Redis is reachable.",
        ) from exc

    if created:
        try:
            await refresh_catalogs_for_credentials(
                payload_to_store, user_settings=user_settings, auth_key=verified_auth_key
            )
        except Exception as exc:  # pragma: no cover - remote dependency
            logger.error(f"[{redact_token(token)}] Initial catalog refresh failed: {{}}", exc, exc_info=True)
            await token_store.delete_token(token=token)
            raise HTTPException(
                status_code=502,
                detail="Credentials verified, but Watchly couldn't refresh your catalogs yet. Please try again.",
            ) from exc

    base_url = settings.HOST_NAME
    # New URL structure (Settings stored in Token)
    manifest_url = f"{base_url}/{token}/manifest.json"

    expires_in = settings.TOKEN_TTL_SECONDS if settings.TOKEN_TTL_SECONDS > 0 else None

    return TokenResponse(
        token=token,
        manifestUrl=manifest_url,
        expiresInSeconds=expires_in,
    )


@router.post("/verify", status_code=200)
async def verify_user(payload: TokenRequest):
    """Verify if a Watchly user exists."""
    watchly_username = payload.watchly_username.strip() if payload.watchly_username else None
    watchly_password = payload.watchly_password

    if not watchly_username or not watchly_password:
        raise HTTPException(status_code=400, detail="Watchly username and password required.")

    payload_to_derive = {
        "watchly_username": watchly_username,
        "watchly_password": watchly_password,
        "username": None,
        "password": None,
        "authKey": None,
    }

    token = token_store.derive_token(payload_to_derive)
    exists = await token_store.get_payload(token)

    if not exists:
        raise HTTPException(status_code=404, detail="Account not found.")

    return {"found": True, "token": token, "settings": exists.get("settings")}


@router.delete("/", status_code=200)
async def delete_token(payload: TokenRequest):
    """Delete a token based on provided credentials."""
    # Stremio Credentials
    stremio_username = payload.username.strip() if payload.username else None
    stremio_password = payload.password
    stremio_auth_key = payload.authKey.strip() if payload.authKey else None

    # Watchly Credentials
    watchly_username = payload.watchly_username.strip() if payload.watchly_username else None
    watchly_password = payload.watchly_password

    if stremio_auth_key and stremio_auth_key.startswith('"') and stremio_auth_key.endswith('"'):
        stremio_auth_key = stremio_auth_key[1:-1].strip()

    # Need either Watchly creds OR Stremio creds (for legacy)
    if (
        not (watchly_username and watchly_password)
        and not stremio_auth_key
        and not (stremio_username and stremio_password)
    ):
        raise HTTPException(
            status_code=400,
            detail="Provide Watchly credentials (or Stremio credentials for legacy accounts) to delete account.",
        )

    payload_to_derive = {
        "watchly_username": watchly_username,
        "watchly_password": watchly_password,
        "username": stremio_username,
        "password": stremio_password,
        "authKey": stremio_auth_key,
    }

    try:
        # We don't verify credentials with Stremio here, we just check if we have a token for them.
        # If the user provides wrong credentials, we'll derive a wrong token, which won't exist in Redis.
        # That's fine, we can just say "deleted" or "not found".
        # However, to be nice, we might want to say "Settings deleted" even if they didn't exist.
        # But if we want to be strict, we could check existence.
        # Let's just try to delete.

        token = token_store.derive_token(payload_to_derive)
        await token_store.delete_token(token)
        logger.info(f"[{redact_token(token)}] Token deleted (if existed)")
        return {"detail": "Settings deleted successfully"}
    except (redis_exceptions.RedisError, OSError) as exc:
        logger.error("Token deletion failed: {}", exc)
        raise HTTPException(
            status_code=503,
            detail="Token deletion is temporarily unavailable. Please try again once Redis is reachable.",
        ) from exc
