from fastapi import APIRouter, HTTPException

from app.core.config import settings
from app.core.security import TOKEN_PATTERN
from app.services.context import extract_settings
from app.services.nuvio import nuvio_service
from app.services.profile.service import ProfileService
from app.services.token_store import token_store

router = APIRouter(tags=["Nuvio"])


@router.post("/{token}/nuvio/install")
async def install_on_nuvio(token: str) -> dict[str, str]:
    """Install this account's manifest into the Nuvio profile it reads from.

    Uses the session stored with the account, so a connected user never types
    their Nuvio password twice. 409 tells the page to fall back to the sign-in modal.
    """
    if not TOKEN_PATTERN.match(token):
        raise HTTPException(status_code=400, detail="Malformed token.")
    token = await token_store.resolve_alias(token)
    credentials = await token_store.get_user_data(token)
    if not credentials:
        raise HTTPException(status_code=404, detail="Token not found. Please reconfigure the addon.")

    user_settings = extract_settings(credentials)
    identity = (credentials.get("identities") or {}).get("nuvio") or ""
    if not (user_settings.nuvio_access_token and user_settings.nuvio_profile_id and identity):
        raise HTTPException(status_code=409, detail="No Nuvio account is connected to this install.")

    access_token, _ = await ProfileService().nuvio_access_token(token, user_settings)
    if not access_token:
        raise HTTPException(status_code=502, detail="Nuvio did not renew the stored session. Try again shortly.")

    manifest_url = f"{settings.HOST_NAME}/{token}/manifest.json"
    status = await nuvio_service.install_addon(
        access_token, identity.split(":", 1)[0], user_settings.nuvio_profile_id, manifest_url
    )
    return {"status": status, "profile": user_settings.nuvio_profile_name or str(user_settings.nuvio_profile_id)}
