from urllib.parse import unquote, urlparse

from fastapi import APIRouter, HTTPException
from loguru import logger

from app.api.models.stremio_profiles import (
    StremioCredentialsRequest,
    StremioProfileAddonInstallRequest,
    StremioProfileAddonInstallResponse,
    StremioProfileAuthRequest,
    StremioProfileAuthResponse,
    StremioProfileInstance,
    StremioProfileInstancesResponse,
    StremioProfilesResponse,
)
from app.core.config import settings
from app.services.auth import auth_service
from app.services.manifest import manifest_service
from app.services.stremio.service import StremioBundle
from app.services.token_store import token_store

router = APIRouter(prefix="/stremio/profiles", tags=["Stremio Profiles"])


@router.post("/", response_model=StremioProfilesResponse)
async def list_profiles(payload: StremioCredentialsRequest) -> StremioProfilesResponse:
    bundle = StremioBundle()
    try:
        auth_key = await auth_service.require_auth_key(bundle, payload.model_dump())
        profiles = await bundle.auth.get_profiles(auth_key)
        return StremioProfilesResponse(profiles=profiles)
    except HTTPException:
        raise
    except Exception as exc:
        logger.info(f"Could not load Stremio profiles: {exc}")
        raise HTTPException(status_code=400, detail="Could not load Stremio profiles.")
    finally:
        await bundle.close()


@router.post("/instances", response_model=StremioProfileInstancesResponse)
async def list_profile_instances(payload: StremioCredentialsRequest) -> StremioProfileInstancesResponse:
    bundle = StremioBundle()
    try:
        auth_key = await auth_service.require_auth_key(bundle, payload.model_dump())
        profiles = await bundle.auth.get_profiles(auth_key)
        current = await bundle.auth.get_user_info(auth_key)
        master = next((profile for profile in profiles if profile.is_master), None)
        if master is None:
            raise ValueError("The Stremio primary profile could not be identified")

        current_profile_id = current.get("profile_id")
        visible_profiles = (
            profiles
            if not current_profile_id or current_profile_id == master.id
            else [profile for profile in profiles if profile.id == current_profile_id]
        )
        instances = []
        for profile in visible_profiles:
            identity_id = master.id if profile.id == master.id else f"{master.id}:{profile.id}"
            token = await token_store.get_token_for_identity("stremio", identity_id)
            instances.append(
                StremioProfileInstance(profile_id=profile.id, profile_name=profile.name, token=token)
            )
        return StremioProfileInstancesResponse(instances=instances)
    except HTTPException:
        raise
    except Exception as exc:
        logger.info(f"Could not list profile-specific Watchly instances: {exc}")
        raise HTTPException(status_code=400, detail="Could not load Watchly instances for this Stremio account.")
    finally:
        await bundle.close()


@router.post("/authenticate", response_model=StremioProfileAuthResponse)
async def authenticate_profile(payload: StremioProfileAuthRequest) -> StremioProfileAuthResponse:
    bundle = StremioBundle()
    try:
        auth_key = await auth_service.require_auth_key(bundle, payload.model_dump())
        profiles = await bundle.auth.get_profiles(auth_key)
        requested_profile = next((profile for profile in profiles if profile.id == payload.profile_id), None)
        if requested_profile is None:
            raise ValueError("The selected Stremio profile no longer exists")

        # Stremio returns no replacement key when the requested profile is already
        # active. In that case the submitted key is already the correct scoped key.
        profile_auth_key = (
            auth_key
            if requested_profile.selected
            else await bundle.auth.authenticate_profile(auth_key, payload.profile_id, payload.pin)
        )
        profile_info = await bundle.auth.get_user_info(profile_auth_key)
        selected_profile_id = profile_info.get("profile_id")
        if selected_profile_id and selected_profile_id != payload.profile_id:
            raise ValueError("Stremio activated a different profile than the one requested")
        logger.info("Authenticated a Stremio profile for a profile-specific Watchly configuration")
        return StremioProfileAuthResponse(
            authKey=profile_auth_key,
            profile_id=selected_profile_id or payload.profile_id,
            profile_name=profile_info.get("profile_name") or requested_profile.name,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.info(f"Could not authenticate Stremio profile: {exc}")
        raise HTTPException(status_code=400, detail="Could not unlock the selected Stremio profile.")
    finally:
        await bundle.close()


@router.post("/install-addon", response_model=StremioProfileAddonInstallResponse)
async def install_profile_addon(payload: StremioProfileAddonInstallRequest) -> StremioProfileAddonInstallResponse:
    bundle = StremioBundle()
    try:
        profile_info = await bundle.auth.get_user_info(payload.authKey)
        if profile_info.get("profile_id") != payload.profile_id:
            raise ValueError("The Stremio session belongs to a different profile")

        token = _manifest_token(payload.manifest_url)
        manifest = await manifest_service.get_manifest_for_token(token)
        installed = await bundle.addons.install_addon(payload.authKey, payload.manifest_url, manifest)
        if not installed:
            raise ValueError("Stremio rejected the addon collection update")
        logger.info("Installed a profile-specific Watchly instance in Stremio")
        return StremioProfileAddonInstallResponse(success=True)
    except Exception as exc:
        logger.info(f"Could not install profile-specific Watchly instance: {exc}")
        raise HTTPException(status_code=400, detail="Could not install Watchly in the selected Stremio profile.")
    finally:
        await bundle.close()


def _manifest_token(manifest_url: str) -> str:
    parsed = urlparse(manifest_url)
    configured = urlparse(settings.HOST_NAME)
    parsed_port = parsed.port or (443 if parsed.scheme == "https" else 80)
    configured_port = configured.port or (443 if configured.scheme == "https" else 80)
    if (parsed.scheme, parsed.hostname, parsed_port) != (configured.scheme, configured.hostname, configured_port):
        raise ValueError("Manifest URL does not belong to this Watchly server")
    if parsed.query or parsed.fragment:
        raise ValueError("Manifest URL must not contain a query or fragment")

    base_path = configured.path.rstrip("/")
    path = unquote(parsed.path)
    prefix = f"{base_path}/"
    suffix = "/manifest.json"
    if not path.startswith(prefix) or not path.endswith(suffix):
        raise ValueError("Invalid Watchly manifest URL")
    token = path[len(prefix) : -len(suffix)]
    if not token or "/" in token:
        raise ValueError("Invalid Watchly manifest token")
    return token
