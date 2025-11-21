from fastapi import APIRouter, HTTPException, Request
from loguru import logger
from pydantic import BaseModel, Field

from app.config import settings
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


@router.post("/", response_model=TokenResponse)
async def create_token(payload: TokenRequest, request: Request) -> TokenResponse:
    username = payload.username.strip() if payload.username else None
    password = payload.password
    auth_key = payload.authKey.strip() if payload.authKey else None

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

    try:
        token = await token_store.store_payload(payload_to_store)
    except RuntimeError as exc:
        logger.error("Token storage failed: {}", exc)
        raise HTTPException(
            status_code=500,
            detail="Server configuration error: TOKEN_SALT must be set to a secure value.",
        ) from exc
    base_url = str(request.base_url).rstrip("/")
    manifest_url = f"{base_url}/{token}/manifest.json"

    expires_in = settings.TOKEN_TTL_SECONDS if settings.TOKEN_TTL_SECONDS > 0 else None

    return TokenResponse(
        token=token,
        manifestUrl=manifest_url,
        expiresInSeconds=expires_in,
    )
