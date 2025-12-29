from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from loguru import logger

from app.core.config import settings
from app.services.stremio.client import StremioClient


def match_hostname(url: str, hostname: str) -> bool:
    """Return True if the URL host matches the target host (scheme-agnostic)."""
    try:
        url_host = urlparse(url if "://" in url else f"https://{url}").hostname
        target_host = urlparse(hostname if "://" in hostname else f"https://{hostname}").hostname
        return bool(url_host and target_host and url_host.lower() == target_host.lower())
    except Exception as e:
        logger.debug(f"Failed to parse or match hostname for URL {url} against {hostname}: {e}")
        return False


class StremioAddonService:
    """
    Handles fetching and updating Stremio addon collections.
    """

    def __init__(self, client: StremioClient):
        self.client = client

    async def get_addons(self, auth_key: str) -> list[dict[str, Any]]:
        """Fetch the user's addon collection."""
        payload = {
            "type": "AddonCollectionGet",
            "authKey": auth_key,
            "update": True,
        }
        try:
            data = await self.client.post("/api/addonCollectionGet", json=payload)

            if "error" in data:
                error = data["error"]
                message = error.get("message") if isinstance(error, dict) else str(error)
                raise ValueError(f"Stremio Addon Error: {message}")

            return data.get("result", {}).get("addons", [])
        except Exception as e:
            logger.exception(f"Failed to fetch addons: {e}")
            raise

    async def update_addon_collection(self, auth_key: str, addons: list[dict[str, Any]]) -> bool:
        """Update the user's entire addon collection."""
        payload = {
            "type": "AddonCollectionSet",
            "authKey": auth_key,
            "addons": addons,
        }
        try:
            data = await self.client.post("/api/addonCollectionSet", json=payload)
            return data.get("result", {}).get("success", False)
        except Exception as e:
            logger.exception(f"Failed to update addon collection: {e}")
            return False

    async def update_catalogs(self, auth_key: str, catalogs: list[dict[str, Any]]) -> bool:
        """
        Inject dynamic catalogs into the installed Watchly addon.
        """

        addons = await self.get_addons(auth_key)

        found = False
        for addon in addons:
            if addon.get("manifest", {}).get("id") == settings.ADDON_ID and match_hostname(
                addon.get("transportUrl"), settings.HOST_NAME
            ):
                addon["manifest"]["catalogs"] = catalogs
                # also update description with updated time
                addon["manifest"]["description"] = (
                    "Movie and series recommendations based on your Stremio library.\nLast Updated on: "
                    f" {datetime.now(timezone.utc).strftime('%d %B %Y, %H:%M:%S')} UTC"
                )
                found = True
                break

        if not found:
            logger.warning(f"Addon {settings.ADDON_ID} not found in user collection; cannot update catalogs.")
            return False

        return await self.update_addon_collection(auth_key, addons)

    async def is_addon_installed(self, auth_key: str) -> bool:
        """Check if the Watchly addon is present in the user's collection."""

        addons = await self.get_addons(auth_key)
        for addon in addons:
            if addon.get("manifest", {}).get("id") == settings.ADDON_ID and match_hostname(
                addon.get("transportUrl"), settings.HOST_NAME
            ):
                return True
        return False
