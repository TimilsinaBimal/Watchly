import secrets
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from loguru import logger

from app.core.config import settings
from app.services.trakt import trakt_service

router = APIRouter(tags=["OAuth"])

# Short-lived cookie name + lifetime for OAuth CSRF state.
_OAUTH_STATE_COOKIE_PREFIX = "watchly_oauth_state_"
_OAUTH_STATE_TTL_SECONDS = 600  # 10 minutes


def _set_state_cookie(response, provider: str, state: str) -> None:
    response.set_cookie(
        key=f"{_OAUTH_STATE_COOKIE_PREFIX}{provider}",
        value=state,
        max_age=_OAUTH_STATE_TTL_SECONDS,
        httponly=True,
        secure=settings.APP_ENV == "production",
        samesite="lax",
        path="/",
    )


def _verify_state(request: Request, provider: str, state: str | None) -> None:
    expected = request.cookies.get(f"{_OAUTH_STATE_COOKIE_PREFIX}{provider}")
    if not state or not expected or not secrets.compare_digest(state, expected):
        raise HTTPException(status_code=400, detail="Invalid or missing OAuth state. Please try connecting again.")


# ── Trakt OAuth ──────────────────────────────────────────────────────────────

TRAKT_AUTH_URL = "https://trakt.tv/oauth/authorize"


@router.get("/auth/trakt")
async def trakt_auth_redirect(request: Request):
    """Redirect user to Trakt authorization page."""
    if not settings.TRAKT_CLIENT_ID:
        raise HTTPException(status_code=501, detail="Trakt integration is not configured on this server.")

    redirect_uri = f"{settings.HOST_NAME}/auth/trakt/callback"
    state = secrets.token_urlsafe(32)
    params = urlencode(
        {
            "response_type": "code",
            "client_id": settings.TRAKT_CLIENT_ID,
            "redirect_uri": redirect_uri,
            "state": state,
        }
    )
    response = RedirectResponse(f"{TRAKT_AUTH_URL}?{params}")
    _set_state_cookie(response, "trakt", state)
    return response


@router.get("/auth/trakt/callback", response_class=HTMLResponse)
async def trakt_callback(request: Request, code: str, state: str | None = None):
    """Handle Trakt OAuth callback, exchange code for tokens."""
    if not settings.TRAKT_CLIENT_ID or not settings.TRAKT_CLIENT_SECRET:
        raise HTTPException(status_code=501, detail="Trakt integration is not configured on this server.")

    _verify_state(request, "trakt", state)

    redirect_uri = f"{settings.HOST_NAME}/auth/trakt/callback"

    try:
        token_data = await trakt_service.exchange_code(code, redirect_uri)
        access_token = token_data.get("access_token", "")
        refresh_token = token_data.get("refresh_token", "")

        # Fetch username for display
        user_info = await trakt_service.get_user_info(access_token)
        username = user_info.get("user", {}).get("username") or user_info.get("username", "Unknown")
    except Exception as e:
        logger.error(f"Trakt OAuth callback failed: {e}")
        return HTMLResponse(_oauth_error_page("Trakt", str(e)))

    return HTMLResponse(
        _oauth_success_page(
            provider="trakt",
            username=username,
            tokens={"access_token": access_token, "refresh_token": refresh_token},
        )
    )


# ── Simkl OAuth ──────────────────────────────────────────────────────────────

SIMKL_AUTH_URL = "https://simkl.com/oauth/authorize"
SIMKL_TOKEN_URL = "https://api.simkl.com/oauth/token"


@router.get("/auth/simkl")
async def simkl_auth_redirect(request: Request):
    """Redirect user to Simkl authorization page."""
    if not settings.SIMKL_CLIENT_ID or not settings.SIMKL_CLIENT_SECRET:
        raise HTTPException(status_code=501, detail="Simkl integration is not configured on this server.")

    redirect_uri = f"{settings.HOST_NAME}/auth/simkl/callback"
    state = secrets.token_urlsafe(32)
    params = urlencode(
        {
            "response_type": "code",
            "client_id": settings.SIMKL_CLIENT_ID,
            "redirect_uri": redirect_uri,
            "state": state,
        }
    )
    response = RedirectResponse(f"{SIMKL_AUTH_URL}?{params}")
    _set_state_cookie(response, "simkl", state)
    return response


@router.get("/auth/simkl/callback", response_class=HTMLResponse)
async def simkl_callback(request: Request, code: str, state: str | None = None):
    """Handle Simkl OAuth callback, exchange code for tokens."""
    if not settings.SIMKL_CLIENT_ID or not settings.SIMKL_CLIENT_SECRET:
        raise HTTPException(status_code=501, detail="Simkl integration is not configured on this server.")

    _verify_state(request, "simkl", state)

    redirect_uri = f"{settings.HOST_NAME}/auth/simkl/callback"

    try:
        from httpx import AsyncClient

        async with AsyncClient(timeout=15) as client:
            resp = await client.post(
                SIMKL_TOKEN_URL,
                json={
                    "code": code,
                    "client_id": settings.SIMKL_CLIENT_ID,
                    "client_secret": settings.SIMKL_CLIENT_SECRET,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
                follow_redirects=True,
            )
            resp.raise_for_status()
            token_data = resp.json()

        access_token = token_data.get("access_token", "")

        # Fetch username for display
        async with AsyncClient(timeout=15) as client:
            resp = await client.get(
                "https://api.simkl.com/users/settings",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "simkl-api-key": settings.SIMKL_CLIENT_ID,
                },
                follow_redirects=True,
            )
            resp.raise_for_status()
            user_info = resp.json()
            username = user_info.get("user", {}).get("name") or user_info.get("account", {}).get("id", "Unknown")
    except Exception as e:
        logger.error(f"Simkl OAuth callback failed: {e}")
        return HTMLResponse(_oauth_error_page("Simkl", str(e)))

    return HTMLResponse(
        _oauth_success_page(
            provider="simkl",
            username=str(username),
            tokens={"access_token": access_token},
        )
    )


# ── HTML helpers ─────────────────────────────────────────────────────────────


def _oauth_success_page(provider: str, username: str, tokens: dict[str, str]) -> str:
    """Generate a callback page that sends tokens back to the opener window."""
    import json
    from urllib.parse import urlparse

    payload = json.dumps({"provider": provider, "username": username, "tokens": tokens})
    # Pin postMessage target to the configured app origin so we never broadcast
    # tokens to whatever origin the popup happens to be on.
    parsed = urlparse(settings.HOST_NAME or "")
    target_origin = json.dumps(f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else "/")
    return f"""<!DOCTYPE html>
        <html><head><title>{provider.title()} Connected</title></head>
        <body>
        <h2>Connected as {username}</h2>
        <p>You can close this window.</p>
        <script>
        if (window.opener) {{
            window.opener.postMessage({payload}, {target_origin});
        }}
        setTimeout(function() {{ window.close(); }}, 2000);
        </script>
        </body></html>"""


def _oauth_error_page(provider: str, error: str) -> str:
    return f"""<!DOCTYPE html>
<html><head><title>{provider.title()} Error</title></head>
<body>
<h2>{provider.title()} login failed</h2>
<p>{error}</p>
<p>Please close this window and try again.</p>
</body></html>"""
