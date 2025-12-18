from loguru import logger

from app.core.config import settings

from .client import StremioClient


class AddonManager:
    """Handles addon installation checks and updates."""

    def __init__(self, client: StremioClient):
        self.client = client

    async def get_addons(self, auth_key: str) -> list[dict]:
        url = f"{self.client.base_url}/api/addonCollectionGet"
        payload = {"type": "AddonCollectionGet", "authKey": auth_key, "update": True}
        data = await self.client.post_with_retries(url, payload)
        if "error" in data:
            raise ValueError(f"Stremio: {data['error']}")
        return data.get("result", {}).get("addons", [])

    async def update_catalogs(self, auth_key: str, catalogs: list[dict]):
        addons = await self.get_addons(auth_key)
        target_found = False

        for addon in addons:
            manifest = addon.get("manifest", {})
            if manifest.get("id") == settings.ADDON_ID:
                # Check transport URL hostname match if needed (simplified here)
                manifest["catalogs"] = catalogs
                target_found = True
                break

        if target_found:
            url = f"{self.client.base_url}/api/addonCollectionSet"
            await self.client.post_with_retries(
                url, {"type": "AddonCollectionSet", "authKey": auth_key, "addons": addons}
            )

    async def is_addon_installed(self, auth_key: str) -> bool:
        """Check if the Watchly addon is installed for the user."""
        try:
            addons = await self.get_addons(auth_key)
            for addon in addons:
                manifest = addon.get("manifest", {})
                if manifest.get("id") == settings.ADDON_ID:
                    return True
            return False
        except Exception as e:
            logger.warning(f"Failed to check addon installation status: {e}")
            return False
