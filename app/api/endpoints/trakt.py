"""
Trakt OAuth and token-creation endpoints.

Flow:
1. GET  /tokens/trakt/config        → returns client_id + whether Trakt is configured
2. GET  /tokens/trakt/authorize     → returns the Trakt OAuth2 URL for the popup
3. GET  /tokens/trakt/callback      → Trakt redirects here after user approves;
                                       exchanges code for tokens, then posts a
                                       message to the opener window and closes.
4. POST /tokens/trakt               → Creates/updates a Watchly account using a
                                       Trakt access_token (same body shape as
                                       the main /tokens/ endpoint plus trakt_access_token).
5. POST /tokens/trakt/identity      → Lightweight identity-check (returns user info
                                       + existing settings if account exists).
"""

import secrets
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from loguru import logger
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.security import redact_token
from app.core.settings import CatalogConfig, PosterRatingConfig, UserSettings, get_default_settings
from app.services.manifest import manifest_service
from app.services.token_store import token_store
from app.services.trakt.service import TraktBundle

router = APIRouter(prefix="/tokens/trakt", tags=["trakt"])

# OAuth state values are stored in Redis with a short TTL so they work
# correctly across multiple workers and don't accumulate indefinitely.
_OAUTH_STATE_TTL = 600  # 10 minutes


async def _store_oauth_state(state: str) -> None:
    from app.services.redis_service import redis_service
    await redis_service.set(f"watchly:oauth_state:trakt:{state}", state, _OAUTH_STATE_TTL)


async def _consume_oauth_state(state: str) -> bool:
    """Returns True and deletes the state if valid, False otherwise."""
    from app.services.redis_service import redis_service
    key = f"watchly:oauth_state:trakt:{state}"
    value = await redis_service.get(key)
    if value:
        await redis_service.delete(key)
        return True
    return False


def _get_bundle(access_token: str | None = None) -> TraktBundle:
    client_id = settings.TRAKT_CLIENT_ID
    client_secret = settings.TRAKT_CLIENT_SECRET
    if not client_id or not client_secret:
        raise HTTPException(
            status_code=503,
            detail="Trakt integration is not configured on this server. Set TRAKT_CLIENT_ID and TRAKT_CLIENT_SECRET.",
        )
    redirect_uri = f"{settings.HOST_NAME}/tokens/trakt/callback"
    return TraktBundle(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        access_token=access_token,
    )


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class TraktTokenRequest(BaseModel):
    trakt_access_token: str = Field(..., description="Trakt OAuth2 access token")
    trakt_refresh_token: str | None = Field(default=None, description="Trakt OAuth2 refresh token")
    trakt_expires_at: int | None = Field(default=None, description="Unix timestamp when access token expires")
    catalogs: list[CatalogConfig] | None = Field(default=None)
    language: str = Field(default="en-US")
    poster_rating: PosterRatingConfig | None = Field(default=None)
    excluded_movie_genres: list[str] = Field(default_factory=list)
    excluded_series_genres: list[str] = Field(default_factory=list)
    popularity: str = Field(default="balanced")
    year_min: int = Field(default=2010)
    year_max: int = Field(default=2025)
    sorting_order: str = Field(default="default")
    simkl_api_key: str | None = Field(default=None)
    gemini_api_key: str | None = Field(default=None)
    tmdb_api_key: str | None = Field(default=None)


class TraktTokenResponse(BaseModel):
    token: str
    manifestUrl: str
    expiresInSeconds: int | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/config")
async def trakt_config():
    """Return whether Trakt is configured and the client_id (needed for the popup)."""
    configured = bool(settings.TRAKT_CLIENT_ID and settings.TRAKT_CLIENT_SECRET)
    return {
        "configured": configured,
        "client_id": settings.TRAKT_CLIENT_ID if configured else None,
    }


@router.get("/authorize")
async def trakt_authorize():
    """Return the Trakt OAuth2 authorization URL for the frontend popup."""
    bundle = _get_bundle()
    state = secrets.token_urlsafe(16)
    await _store_oauth_state(state)
    url, _ = bundle.auth.get_authorize_url(state=state)
    await bundle.close()
    return {"url": url, "state": state}


@router.get("/callback", response_class=HTMLResponse)
async def trakt_callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None):
    """
    Trakt redirects here after the user approves (or denies) the app.
    We exchange the code for tokens and post a message back to the opener
    window, then close the popup.
    """
    # --- error from Trakt ---
    if error or not code:
        return HTMLResponse(_popup_close_html(success=False, error=error or "Authorization cancelled"))

    # --- verify state to prevent CSRF ---
    if not state or not await _consume_oauth_state(state):
        return HTMLResponse(_popup_close_html(success=False, error="Invalid OAuth state. Please try again."))

    # --- exchange code for tokens ---
    try:
        bundle = _get_bundle()
        token_data = await bundle.auth.exchange_code(code)
        await bundle.close()
    except Exception as exc:
        logger.error(f"Trakt callback: token exchange failed: {exc}")
        return HTMLResponse(_popup_close_html(success=False, error="Token exchange failed"))

    access_token = token_data.get("access_token")
    refresh_token = token_data.get("refresh_token")
    expires_in = token_data.get("expires_in", 7776000)  # default 90 days

    if not access_token:
        return HTMLResponse(_popup_close_html(success=False, error="No access token received"))

    # Calculate expiry unix timestamp
    import time
    expires_at = int(time.time()) + expires_in

    return HTMLResponse(
        _popup_close_html(
            success=True,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at,
        )
    )


@router.post("/identity", status_code=200)
async def trakt_identity(payload: TraktTokenRequest):
    """
    Validate the Trakt access token, return user info and existing settings.
    """
    bundle = _get_bundle(access_token=payload.trakt_access_token)
    try:
        user_info = await bundle.user.get_user_info()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid Trakt access token: {exc}") from exc
    finally:
        await bundle.close()

    username = user_info.get("username") or user_info.get("name") or "trakt_user"
    # Use a Trakt-namespaced user_id so it can't clash with Stremio IDs
    user_id = f"trakt:{username}"

    token = token_store.get_token_from_user_id(user_id)
    user_data = await token_store.get_user_data(token)
    exists = bool(user_data)

    response: dict[str, Any] = {
        "user_id": user_id,
        "username": username,
        "display": user_info.get("name") or username,
        "exists": exists,
    }
    if exists and user_data:
        raw_settings = user_data.get("settings", {})
        try:
            user_settings = UserSettings(**raw_settings)
            response["settings"] = user_settings.model_dump()
        except Exception as e:
            logger.warning(f"Failed to normalise settings for {user_id}: {e}")
            response["settings"] = raw_settings

    return response


@router.post("/", response_model=TraktTokenResponse)
async def create_trakt_token(payload: TraktTokenRequest, request: Request):
    """
    Create or update a Watchly account backed by a Trakt access token.
    The library is fetched from Trakt; everything else behaves like the
    Stremio-based token endpoint.
    """
    bundle = _get_bundle(access_token=payload.trakt_access_token)

    try:
        user_info = await bundle.user.get_user_info()
    except Exception as exc:
        await bundle.close()
        raise HTTPException(status_code=400, detail=f"Invalid Trakt access token: {exc}") from exc

    username = user_info.get("username") or user_info.get("name") or "trakt_user"
    user_id = f"trakt:{username}"

    token = token_store.get_token_from_user_id(user_id)
    existing_data = await token_store.get_user_data(token)

    default_settings = get_default_settings()
    user_settings = UserSettings(
        language=payload.language or default_settings.language,
        catalogs=payload.catalogs if payload.catalogs else default_settings.catalogs,
        poster_rating=payload.poster_rating,
        excluded_movie_genres=payload.excluded_movie_genres,
        excluded_series_genres=payload.excluded_series_genres,
        year_min=payload.year_min,
        year_max=payload.year_max,
        popularity=payload.popularity,
        sorting_order=payload.sorting_order,
        simkl_api_key=payload.simkl_api_key,
        gemini_api_key=payload.gemini_api_key,
        tmdb_api_key=payload.tmdb_api_key,
    )

    payload_to_store: dict[str, Any] = {
        "auth_provider": "trakt",
        # authKey stores the Trakt access token (encrypted by token_store)
        "authKey": payload.trakt_access_token,
        "trakt_refresh_token": payload.trakt_refresh_token,
        "trakt_expires_at": payload.trakt_expires_at,
        "trakt_username": username,
        "email": user_info.get("name") or username,
        "settings": user_settings.model_dump(),
        "last_updated": existing_data.get("last_updated") if existing_data else datetime.now(timezone.utc).isoformat(),
    }

    token = await token_store.store_user_data(user_id, payload_to_store)
    account_status = "updated" if existing_data else "created"
    logger.info(f"[{redact_token(token)}] Trakt account {account_status} for user {user_id}")

    # Pre-cache library using Trakt data
    try:
        library_items = await bundle.library.get_library_items()
        # Use the shared manifest caching pathway, passing library_items directly
        await manifest_service.cache_library_and_profiles_from_items(library_items, user_settings, token)
        logger.info(f"[{redact_token(token)}] Trakt library cached ({len(library_items.get('watched', []))} items)")
    except Exception as exc:
        logger.warning(f"[{redact_token(token)}] Failed to pre-cache Trakt library: {exc}. Will cache on demand.")
    finally:
        await bundle.close()

    base_url = settings.HOST_NAME
    manifest_url = f"{base_url}/{token}/manifest.json"
    expires_in = settings.TOKEN_TTL_SECONDS if settings.TOKEN_TTL_SECONDS > 0 else None

    return TraktTokenResponse(token=token, manifestUrl=manifest_url, expiresInSeconds=expires_in)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _popup_close_html(
    success: bool,
    error: str | None = None,
    access_token: str | None = None,
    refresh_token: str | None = None,
    expires_at: int | None = None,
) -> str:
    """
    Minimal HTML page that posts a message to the opener and closes itself.
    The frontend listens for this message via window.addEventListener('message', ...).
    """
    if success:
        payload_js = (
            f"{{ type: 'trakt_auth_success', "
            f"access_token: {_js_str(access_token)}, "
            f"refresh_token: {_js_str(refresh_token)}, "
            f"expires_at: {expires_at or 'null'} }}"
        )
    else:
        payload_js = f"{{ type: 'trakt_auth_error', error: {_js_str(error or 'Unknown error')} }}"

    return f"""<!DOCTYPE html>
<html>
<head><title>Trakt Authorization</title></head>
<body>
<p style="font-family:sans-serif;text-align:center;margin-top:3rem">
  {'Authorization successful! You can close this window.' if success else f'Authorization failed: {error}'}
</p>
<script>
  try {{
    if (window.opener) {{
      window.opener.postMessage({payload_js}, window.location.origin);
    }}
  }} catch(e) {{}}
  setTimeout(function() {{ window.close(); }}, 1000);
</script>
</body>
</html>"""


def _js_str(value: str | None) -> str:
    import json
    return json.dumps(value)
