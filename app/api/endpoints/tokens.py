import httpx
from redis import exceptions as redis_exceptions
from fastapi import APIRouter, HTTPException, Request
from loguru import logger
from pydantic import BaseModel, Field

from app.config import settings
from app.services.catalog_updater import refresh_catalogs_for_credentials
from app.services.stremio_service import StremioService
from app.services.token_store import token_store

router = APIRouter(prefix="/tokens", tags=["tokens"])


class TokenRequest(BaseModel):
    username: str | None = Field(default=None, description="Stremio username or email")
    password: str | None = Field(default=None, description="Stremio password")
    authKey: str | None = Field(default=None, description="Existing Stremio auth key")
    includeWatched: bool = Field(
        default=False,
        description="If true, recommendations can include watched titles",
    )


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
            detail=str(exc) or "Invalid Stremio credentials or auth key."
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

def _preferred_base_url(request: Request) -> str:
    headers = request.headers

    def _first_header_value(name: str) -> str | None:
        raw = headers.get(name)
        if not raw:
            return None
        # Some proxies send comma-separated lists for chained hops
        return raw.split(",")[0].strip()

    scheme = _first_header_value("x-forwarded-proto") or request.url.scheme
    host = _first_header_value("x-forwarded-host") or headers.get("host") or request.url.netloc
    prefix = _first_header_value("x-forwarded-prefix") or ""
    root_path = request.scope.get("root_path", "")

    base_path = f"{prefix}{root_path}".rstrip("/")
    if base_path and not base_path.startswith("/"):
        base_path = f"/{base_path}"

    base_url = f"{scheme}://{host}"
    if base_path:
        base_url = f"{base_url}{base_path}"

    return base_url.rstrip("/")


@router.post("/", response_model=TokenResponse)
async def create_token(payload: TokenRequest, request: Request) -> TokenResponse:
    username = payload.username.strip() if payload.username else None
    password = payload.password
    auth_key = payload.authKey.strip() if payload.authKey else None
    if auth_key and auth_key.startswith("\"") and auth_key.endswith("\""):
        auth_key = auth_key[1:-1].strip()

    if username and not password:
        raise HTTPException(status_code=400, detail="Password is required when a username is provided.")

    if password and not username:
        raise HTTPException(status_code=400, detail="Username/email is required when a password is provided.")

    if not auth_key and not (username and password):
        raise HTTPException(
            status_code=400,
            detail="Provide either a Stremio auth key or both username and password.",
        )

    payload_to_store = {
        "username": username,
        "password": password,
        "authKey": auth_key,
        "includeWatched": payload.includeWatched,
    }

    verified_auth_key = await _verify_credentials_or_raise(payload_to_store)

    try:
        token, created = await token_store.store_payload(payload_to_store)
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
                payload_to_store, auth_key=verified_auth_key
            )
        except Exception as exc:  # pragma: no cover - remote dependency
            logger.error("Initial catalog refresh failed: {}", exc, exc_info=True)
            await token_store.delete_token(token)
            raise HTTPException(
                status_code=502,
                detail="Credentials verified, but Watchly couldn't refresh your catalogs yet. Please try again.",
            ) from exc
    base_url = _preferred_base_url(request)
    manifest_url = f"{base_url}/{token}/manifest.json"

    expires_in = settings.TOKEN_TTL_SECONDS if settings.TOKEN_TTL_SECONDS > 0 else None

    return TokenResponse(
        token=token,
        manifestUrl=manifest_url,
        expiresInSeconds=expires_in,
    )
