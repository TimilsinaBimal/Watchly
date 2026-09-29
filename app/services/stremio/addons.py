from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from loguru import logger

from app.core.base_client import BaseClient
from app.core.config import settings


def match_hostname(url: str, hostname: str) -> bool:
    """Return True if the URL host matches the target host (scheme-agnostic)."""
    url_host = urlparse(url if "://" in url else f"https://{url}").hostname
    target_host = urlparse(hostname if "://" in hostname else f"https://{hostname}").hostname
    return bool(url_host and target_host and url_host.lower() == target_host.lower())


def _is_this_instance(addon: dict[str, Any]) -> bool:
    return addon.get("manifest", {}).get("id") == settings.ADDON_ID and match_hostname(
        addon.get("transportUrl") or "", settings.HOST_NAME
    )


class StremioAddonService:
    def __init__(self, client: BaseClient):
        self.client = client

    async def get_addons(self, auth_key: str) -> list[dict[str, Any]]:
        payload = {
            "type": "AddonCollectionGet",
            "authKey": auth_key,
            "update": True,
        }
        data = await self.client.post("/api/addonCollectionGet", json=payload)

        if "error" in data:
            error = data["error"]
            message = error.get("message") if isinstance(error, dict) else str(error)
            raise ValueError(f"Stremio Addon Error: {message}")

        return data.get("result", {}).get("addons", [])

    async def update_addon_collection(self, auth_key: str, addons: list[dict[str, Any]]) -> bool:
        payload = {
            "type": "AddonCollectionSet",
            "authKey": auth_key,
            "addons": addons,
        }
        try:
            data = await self.client.post("/api/addonCollectionSet", json=payload)
            return data.get("result", {}).get("success", False)
        except Exception as e:
            logger.warning(f"Failed to update addon collection: {type(e).__name__}")
            return False

    async def install_addon(self, auth_key: str, manifest_url: str, manifest: dict[str, Any]) -> bool:
        """Install or replace this Watchly instance without changing other addons."""
        descriptor = {
            "manifest": manifest,
            "transportUrl": manifest_url,
            "flags": {"official": False, "protected": False},
        }

        addons = await self.get_addons(auth_key)
        addons = [addon for addon in addons if not _is_this_instance(addon)]
        addons.append(descriptor)
        return await self.update_addon_collection(auth_key, addons)

    async def update_description(self, auth_key: str, description: str) -> bool:
        """Update only the addon description."""
        addons = await self.get_addons(auth_key)
        addon = next((a for a in addons if _is_this_instance(a)), None)
        if addon is None:
            logger.warning(f"Addon {settings.ADDON_ID} not found in user collection; cannot update description.")
            return False

        addon["manifest"]["description"] = description
        return await self.update_addon_collection(auth_key, addons)

    async def update_catalogs(self, auth_key: str, catalogs: list[dict[str, Any]]) -> bool:
        """Inject dynamic catalogs into the installed Watchly addon."""
        addons = await self.get_addons(auth_key)
        addon = next((a for a in addons if _is_this_instance(a)), None)
        if addon is None:
            logger.warning(f"Addon {settings.ADDON_ID} not found in user collection; cannot update catalogs.")
            return False

        addon["manifest"]["catalogs"] = catalogs
        now_str = datetime.now(timezone.utc).strftime("%d %B %Y, %H:%M:%S")
        addon["manifest"]["description"] = (
            "Movie and series recommendations based on your Stremio library.\n\n" f"✅ Last Updated: {now_str} UTC"
        )
        return await self.update_addon_collection(auth_key, addons)

    async def is_addon_installed(self, auth_key: str) -> bool:
        return any(_is_this_instance(addon) for addon in await self.get_addons(auth_key))
