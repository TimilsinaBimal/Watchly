from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException

from app.api.models.aiomanager import AIOManagerSyncResponse, AIOManagerValidateInput
from app.api.models.validation import BaseValidationResponse
from app.core.config import settings
from app.core.security import TOKEN_PATTERN
from app.services.aiomanager import AIOManagerError, aiomanager_service, normalize_instance_url
from app.services.context import extract_settings
from app.services.token_store import token_store

router = APIRouter(tags=["AIOManager"])


@router.post("/aiomanager/validate", response_model=BaseValidationResponse)
async def validate_aiomanager(payload: AIOManagerValidateInput) -> BaseValidationResponse:
    """Check that an instance speaks Hydra and accepts the key, before anything is saved."""
    api_key = (payload.api_key or "").strip()
    if not api_key:
        return BaseValidationResponse(valid=False, message="Paste your AIOManager account API key.")

    instance_url = normalize_instance_url(payload.instance_url)
    try:
        version = await aiomanager_service.probe(instance_url)
        await aiomanager_service.check_key(instance_url, api_key)
    except AIOManagerError as error:
        # A verdict rather than a fault: the page renders this next to the field.
        return BaseValidationResponse(valid=False, message=error.detail)

    return BaseValidationResponse(
        valid=True,
        message=f"AIOManager accepts this key{f' (version {version})' if version else ''}.",
    )


@router.post("/{token}/aiomanager/sync", response_model=AIOManagerSyncResponse)
async def sync_to_aiomanager(token: str) -> AIOManagerSyncResponse:
    """Install this account's addon in the user's AIOManager account, or refresh it.

    409 means no manager is connected to this install, so the page can point at the
    field instead of showing a failure it cannot explain.
    """
    if not TOKEN_PATTERN.match(token):
        raise HTTPException(status_code=400, detail="Malformed token.")
    resolved = await token_store.resolve_alias(token)
    credentials = await token_store.get_user_data(resolved)
    if not credentials:
        raise HTTPException(status_code=404, detail="Token not found. Please reconfigure the addon.")

    user_settings = extract_settings(credentials)
    instance_url = normalize_instance_url(user_settings.aiomanager_instance_url or "")
    api_key = (user_settings.aiomanager_api_key or "").strip()
    if not instance_url or not api_key:
        raise HTTPException(status_code=409, detail="No AIOManager account is connected to this install.")

    # Built from this instance's own host name, so what gets pushed is the URL this
    # deployment serves and nothing else. The token in it is the surviving one, so
    # an account that was merged pushes the URL its addon is actually served at.
    # HOST_NAME is not guaranteed to be slash-free, and a doubled slash is a URL the
    # manager would have to redirect before it could read the manifest.
    manifest_url = f"{settings.HOST_NAME.rstrip('/')}/{resolved}/manifest.json"

    # A failed call raises its own AIOManagerError with a status and a sentence, which
    # the handlers in app/core/errors.py log and turn into the response.
    addon_count = await aiomanager_service.reinstall(instance_url, api_key, manifest_url)

    return AIOManagerSyncResponse(status="synced", addon_count=addon_count, instance=urlparse(instance_url).netloc)
