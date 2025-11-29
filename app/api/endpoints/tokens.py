import httpx
from fastapi import APIRouter, HTTPException, Request
from loguru import logger
from pydantic import BaseModel, Field
from redis import exceptions as redis_exceptions

from app.core.config import settings
from app.core.settings import CatalogConfig, UserSettings, encode_settings, get_default_settings
from app.services.catalog_updater import refresh_catalogs_for_credentials
from app.services.stremio_service import StremioService
from app.services.token_store import token_store
from app.utils import redact_token

router = APIRouter(prefix="/tokens", tags=["tokens"])


class TokenRequest(BaseModel):
    username: str | None = Field(default=None, description="Stremio username or email")
    password: str | None = Field(default=None, description="Stremio password")
    authKey: str | None = Field(default=None, description="Existing Stremio auth key")
    catalogs: list[CatalogConfig] | None = Field(default=None, description="Optional catalog configuration")
    language: str = Field(default="en-US", description="Language for TMDB API")


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
    username = payload.username.strip() if payload.username else None
    password = payload.password
    auth_key = payload.authKey.strip() if payload.authKey else None
    if auth_key and auth_key.startswith('"') and auth_key.endswith('"'):
        auth_key = auth_key[1:-1].strip()

    if username and not password:
        raise HTTPException(status_code=400, detail="Password is required when a username is provided.")

    if password and not username:
        raise HTTPException(
            status_code=400,
            detail="Username/email is required when a password is provided.",
        )

    if not auth_key and not (username and password):
        raise HTTPException(
            status_code=400,
            detail="Provide either a Stremio auth key or both username and password.",
        )

    # We only store credentials in Redis, settings go into URL
    payload_to_store = {
        "username": username,
        "password": password,
        "authKey": auth_key,
        # includeWatched is no longer stored here for new tokens
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

    # Construct Settings
    default_settings = get_default_settings()

    user_settings = UserSettings(
        language=payload.language or default_settings.language,
        catalogs=payload.catalogs if payload.catalogs else default_settings.catalogs,
    )

    # encode_settings now includes the "settings:" prefix
    encoded_settings = encode_settings(user_settings)

    if created:
        try:
            await refresh_catalogs_for_credentials(
                payload_to_store, user_settings=user_settings, auth_key=verified_auth_key
            )
        except Exception as exc:  # pragma: no cover - remote dependency
            logger.error(f"[{redact_token(token)}] Initial catalog refresh failed: {{}}", exc, exc_info=True)
            await token_store.delete_token(token)
            raise HTTPException(
                status_code=502,
                detail="Credentials verified, but Watchly couldn't refresh your catalogs yet. Please try again.",
            ) from exc

    base_url = settings.HOST_NAME
    # New URL structure
    manifest_url = f"{base_url}/{encoded_settings}/{token}/manifest.json"

    expires_in = settings.TOKEN_TTL_SECONDS if settings.TOKEN_TTL_SECONDS > 0 else None

    return TokenResponse(
        token=token,
        manifestUrl=manifest_url,
        expiresInSeconds=expires_in,
    )
