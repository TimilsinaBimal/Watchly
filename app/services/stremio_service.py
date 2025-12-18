from typing import Any

from app.core.config import settings
from app.services.stremio.addons import match_hostname
from app.services.stremio.service import StremioBundle

BASE_CATALOGS = [
    {"type": "movie", "id": "watchly.rec", "name": "Top Picks for You", "extra": []},
    {"type": "series", "id": "watchly.rec", "name": "Top Picks for You", "extra": []},
]


class StremioService:
    """
    Proxy class for backward compatibility.
    Delegates all calls to the modular StremioBundle.
    """

    def __init__(
        self,
        username: str = "",
        password: str = "",
        auth_key: str | None = None,
    ):
        self.username = username
        self.password = password
        self._auth_key = auth_key
        self._bundle = StremioBundle()

        if not self._auth_key and (not self.username or not self.password):
            raise ValueError("Username/password or auth key are required")

    async def close(self):
        await self._bundle.close()

    async def _login_for_auth_key(self) -> str:
        key = await self._bundle.auth.login(self.username, self.password)
        self._auth_key = key
        return key

    async def get_auth_key(self) -> str:
        if self._auth_key:
            try:
                await self._bundle.auth.get_user_info(self._auth_key)
                return self._auth_key
            except Exception:
                pass

        if self.username and self.password:
            fresh_key = await self._login_for_auth_key()
            # Note: Persisting refreshed key to token_store is omitted here
            # as it's better handled at a higher level, but for compatibility
            # we could add it back if absolutely necessary.
            return fresh_key

        if not self._auth_key:
            raise ValueError("Stremio auth key is missing and cannot be refreshed.")
        return self._auth_key

    async def get_user_info(self, auth_key: str | None = None) -> dict[str, str]:
        key = auth_key or await self.get_auth_key()
        return await self._bundle.auth.get_user_info(key)

    async def get_user_email(self) -> str:
        info = await self.get_user_info()
        return info.get("email", "")

    async def get_library_items(self) -> dict[str, list[dict[str, Any]]]:
        key = await self.get_auth_key()
        return await self._bundle.library.get_library_items(key)

    async def get_loved_items(self, auth_token: str, media_type: str) -> list[str]:
        return await self._bundle.library.get_likes_by_type(auth_token, media_type, "loved")

    async def get_liked_items(self, auth_token: str, media_type: str) -> list[str]:
        return await self._bundle.library.get_likes_by_type(auth_token, media_type, "liked")

    async def get_addons(self, auth_key: str | None = None) -> list[dict[str, Any]]:
        key = auth_key or await self.get_auth_key()
        return await self._bundle.addons.get_addons(key)

    async def update_addon(self, addons: list[dict[str, Any]], auth_key: str | None = None):
        key = auth_key or await self.get_auth_key()
        return await self._bundle.addons.update_addon_collection(key, addons)

    async def update_catalogs(self, catalogs: list[dict[str, Any]], auth_key: str | None = None):
        key = auth_key or await self.get_auth_key()
        addons = await self.get_addons(key)
        full_catalogs = BASE_CATALOGS + catalogs

        for addon in addons:
            if addon.get("manifest", {}).get("id") == settings.ADDON_ID and match_hostname(
                addon.get("transportUrl"), settings.HOST_NAME
            ):
                addon["manifest"]["catalogs"] = full_catalogs
                break
        return await self.update_addon(addons, key)

    async def is_addon_installed(self, auth_key: str | None = None) -> bool:
        key = auth_key or await self.get_auth_key()
        addons = await self.get_addons(key)
        for addon in addons:
            if addon.get("manifest", {}).get("id") == settings.ADDON_ID and match_hostname(
                addon.get("transportUrl"), settings.HOST_NAME
            ):
                return True
        return False
