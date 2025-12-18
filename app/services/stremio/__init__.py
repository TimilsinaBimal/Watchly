from app.services.token_store import token_store

from .addon import AddonManager
from .client import StremioClient
from .library import LibraryManager


class StremioService:
    """Facade for Stremio functionality."""

    def __init__(self, username: str = "", password: str = "", auth_key: str | None = None):
        self.username = username
        self.password = password
        self._auth_key = auth_key

        self.client = StremioClient()
        self.library = LibraryManager(self.client)
        self.addons = AddonManager(self.client)

    async def get_auth_key(self) -> str:
        if self._auth_key:
            return self._auth_key
        if self.username and self.password:
            url = f"{self.client.base_url}/api/login"
            data = await self.client.post_with_retries(
                url, {"email": self.username, "password": self.password, "type": "Login"}
            )
            if "error" in data:
                raise ValueError(f"Login failed: {data['error']}")

            self._auth_key = data.get("result", {}).get("authKey")
            return self._auth_key
        raise ValueError("No credentials")

    async def get_user_info(self, auth_key: str | None = None) -> dict:
        """
        Get user ID and email.
        If username/password available, logs in to get persistent User ID.
        If only auth_key available, validates it and uses it as User ID (fallback).
        """
        if self.username and self.password:
            auth_key = await self.get_auth_key()  # Ensure logged in
            # We could cache the user info from login, but for now fetch again or store in init
            # NOTE: We can optimize by storing user info on login.
            # Let's do a fresh login or if we just logged in, we lost the user object?
            # Ideally get_auth_key should store user object.

            # Simple approach: Login again or refactor get_auth_key.
            # Rerunning login is safe (idempotent-ish).
            url = f"{self.client.base_url}/api/login"
            data = await self.client.post_with_retries(
                url, {"email": self.username, "password": self.password, "type": "Login"}
            )
            if "error" in data:
                raise ValueError(data["error"])

            user = data.get("result", {}).get("user", {})
            return {"user_id": user.get("_id"), "email": user.get("email")}

        # Auth Key Only Mode
        key = auth_key or self._auth_key
        if key:
            # Validate key by fetching addons
            try:
                await self.addons.get_addons(key)
            except Exception as e:
                raise ValueError(f"Invalid Auth Key: {e}")

            # Fallback: Use AuthKey as UserID since we can't get real ID
            return {"user_id": key, "email": ""}

        raise ValueError("Credentials missing")

    async def get_addons(self, auth_key: str | None = None) -> list:
        key = auth_key or await self.get_auth_key()
        return await self.addons.get_addons(key)

    async def get_library_items(self, use_cache=True) -> dict:
        key = await self.get_auth_key()
        return await self.library.get_library_items(key, use_cache)

    async def update_catalogs(self, catalogs: list, auth_key: str = None):
        key = auth_key or await self.get_auth_key()
        return await self.addons.update_catalogs(key, catalogs)

    async def is_addon_installed(self, auth_key: str = None) -> bool:
        key = auth_key or await self.get_auth_key()
        return await self.addons.is_addon_installed(key)

    async def close(self):
        await self.client.close()
