from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from loguru import logger
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.security import redact_token
from app.core.settings import CatalogConfig, UserSettings, get_default_settings
from app.services.manifest import manifest_service
from app.services.stremio.service import StremioBundle
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


async def _verify_credentials_or_raise(bundle: StremioBundle, auth_key: str) -> str:
    """Ensure the supplied auth key is valid."""
    try:
        await bundle.auth.get_user_info(auth_key)
        return auth_key
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail="Invalid Stremio auth key.",
        ) from exc


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

    bundle = StremioBundle()
    # 1. Establish a valid auth key and fetch user info
    if email and password:
        stremio_auth_key = await bundle.auth.login(email, password)

    try:
        user_info = await bundle.auth.get_user_info(stremio_auth_key)
        user_id = user_info["user_id"]
        resolved_email = user_info.get("email", "")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to verify Stremio identity: {e}")

    # 2. Check if user already exists
    token = token_store.get_token_from_user_id(user_id)
    existing_data = await token_store.get_user_data(token)

    # 3. Construct Settings
    default_settings = get_default_settings()
    user_settings = UserSettings(
        language=payload.language or default_settings.language,
        catalogs=payload.catalogs if payload.catalogs else default_settings.catalogs,
        rpdb_key=payload.rpdb_key.strip() if payload.rpdb_key else None,
        excluded_movie_genres=payload.excluded_movie_genres,
        excluded_series_genres=payload.excluded_series_genres,
    )

    # 4. Prepare payload to store
    payload_to_store = {
        "authKey": stremio_auth_key,
        "email": resolved_email or email or "",
        "settings": user_settings.model_dump(),
    }
    if existing_data:
        payload_to_store["last_updated"] = existing_data.get("last_updated")
    else:
        payload_to_store["last_updated"] = datetime.now(timezone.utc).isoformat()

    if email and password:
        payload_to_store["password"] = password

    # 5. Store user data
    token = await token_store.store_user_data(user_id, payload_to_store)
    account_status = "updated" if existing_data else "created"
    logger.info(f"[{redact_token(token)}] Account {account_status} for user {user_id}")

    # 6. Cache library items and profiles before returning
    # This ensures manifest generation is fast when user installs the addon
    # We wait for caching to complete so everything is ready immediately
    try:
        logger.info(f"[{redact_token(token)}] Caching library and profiles before returning token")
        await manifest_service.cache_library_and_profiles(bundle, stremio_auth_key, user_settings, token)
        logger.info(f"[{redact_token(token)}] Successfully cached library and profiles")
    except Exception as e:
        logger.warning(
            f"[{redact_token(token)}] Failed to cache library and profiles: {e}. "
            "Continuing anyway - will cache on manifest request."
        )
        # Continue even if caching fails - manifest service will handle it

    base_url = settings.HOST_NAME
    manifest_url = f"{base_url}/{token}/manifest.json"
    expires_in = settings.TOKEN_TTL_SECONDS if settings.TOKEN_TTL_SECONDS > 0 else None

    await bundle.close()

    return TokenResponse(
        token=token,
        manifestUrl=manifest_url,
        expiresInSeconds=expires_in,
    )


async def get_stremio_user_data(payload: TokenRequest) -> tuple[str, str]:
    bundle = StremioBundle()
    try:
        email = (payload.email or "").strip() or None
        password = (payload.password or "").strip() or None
        auth_key = (payload.authKey or "").strip() or None

        if email and password:
            try:
                auth_key = await bundle.auth.login(email, password)
                user_info = await bundle.auth.get_user_info(auth_key)
                return user_info["user_id"], user_info.get("email", email)
            except Exception as e:
                logger.error(f"Stremio identity check failed: {e}")
                raise HTTPException(status_code=400, detail="Failed to verify Stremio identity.")
        elif auth_key:
            if auth_key.startswith('"') and auth_key.endswith('"'):
                auth_key = auth_key[1:-1].strip()
            try:
                user_info = await bundle.auth.get_user_info(auth_key)
                return user_info["user_id"], user_info.get("email", "")
            except Exception as e:
                logger.error(f"Stremio identity check failed: {e}")
                raise HTTPException(status_code=400, detail="Invalid Stremio auth key.")
        else:
            raise HTTPException(status_code=400, detail="Credentials required.")
    finally:
        await bundle.close()


@router.post("/stremio-identity", status_code=200)
async def check_stremio_identity(payload: TokenRequest):
    """Fetch user info from Stremio and check if account exists."""
    user_id, email = await get_stremio_user_data(payload)
    try:
        token = token_store.get_token_from_user_id(user_id)
        user_data = await token_store.get_user_data(token)
        exists = bool(user_data)
    except Exception:
        exists = False
        user_data = None

    response = {"user_id": user_id, "email": email, "exists": exists}
    if exists and user_data:
        response["settings"] = user_data.get("settings")
    return response


@router.delete("/", status_code=200)
async def delete_redis_token(payload: TokenRequest):
    """Delete a token based on Stremio credentials."""
    try:
        user_id, _ = await get_stremio_user_data(payload)
        token = token_store.get_token_from_user_id(user_id)
        existing_data = await token_store.get_user_data(token)
        if not existing_data:
            raise HTTPException(status_code=404, detail="Account not found.")

        await token_store.delete_token(token)
        logger.info(f"[{redact_token(token)}] Token deleted for user {user_id}")
        return {"detail": "Settings deleted successfully"}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Token deletion failed: {exc}")
        raise HTTPException(status_code=503, detail="Storage temporarily unavailable.")
