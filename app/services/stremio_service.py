import httpx
from typing import List, Dict, Optional
from loguru import logger
from app.config import settings

import asyncio

BASE_CATALOGS = [
    {"type": "movie", "id": "watchly.rec", "name": "Recommended", "extra": []},
    {"type": "series", "id": "watchly.rec", "name": "Recommended", "extra": []},
]
class StremioService:
    """Service for interacting with Stremio API to fetch user library."""

    def __init__(
        self,
        username: str = "",
        password: str = "",
        auth_key: Optional[str] = None,
    ):
        self.base_url = "https://api.strem.io"
        self.username = username
        self.password = password
        self._auth_key: Optional[str] = auth_key
        if not self._auth_key and (not self.username or not self.password):
            raise ValueError("Username/password or auth key are required")
        # Reuse HTTP client for connection pooling and better performance
        self._client: Optional[httpx.AsyncClient] = None
        self._likes_client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the main Stremio API client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=30.0,
                limits=httpx.Limits(max_keepalive_connections=10, max_connections=50),
            )
        return self._client

    async def _get_likes_client(self) -> httpx.AsyncClient:
        """Get or create the likes API client."""
        if self._likes_client is None:
            self._likes_client = httpx.AsyncClient(
                timeout=30.0,
                limits=httpx.Limits(max_keepalive_connections=10, max_connections=50),
            )
        return self._likes_client

    async def close(self):
        """Close HTTP clients."""
        if self._client:
            await self._client.aclose()
            self._client = None
        if self._likes_client:
            await self._likes_client.aclose()
            self._likes_client = None

    async def _login_for_auth_key(self) -> str:
        """Login with username/password and fetch a fresh auth key."""
        if not self.username or not self.password:
            raise ValueError("Username and password are required to fetch an auth key")
        url = f"{self.base_url}/api/login"
        payload = {
            "email": self.username,
            "password": self.password,
            "type": "Login",
            "facebook": False,
        }

        try:
            client = await self._get_client()
            result = await client.post(url, json=payload)
            result.raise_for_status()
            data = result.json()
            auth_key = data.get("result", {}).get("authKey", "")
            if auth_key:
                logger.info("Successfully authenticated with Stremio")
                self._auth_key = auth_key
            else:
                error_obj = data.get("error") or data
                error_message = "Invalid Stremio username/password."
                if isinstance(error_obj, dict):
                    error_message = error_obj.get("message") or error_message
                elif isinstance(error_obj, str):
                    error_message = error_obj or error_message
                logger.warning(error_obj)
                raise ValueError(f"Stremio: {error_message}")
            return auth_key
        except Exception as e:
            logger.error(f"Error authenticating with Stremio: {e}", exc_info=True)
            raise

    async def get_auth_key(self) -> str:
        """Return a cached auth key or login to retrieve one."""
        if self._auth_key:
            return self._auth_key
        auth_key = await self._login_for_auth_key()
        if not auth_key:
            raise ValueError("Failed to obtain Stremio auth key")
        return auth_key

    async def is_loved(self, auth_key: str, imdb_id: str, media_type: str) -> bool:
        """Check if user has loved a movie or series."""
        if not imdb_id.startswith("tt"):
            return False
        url = "https://likes.stremio.com/api/get_status"
        params = {
            "authToken": auth_key,
            "mediaType": media_type,
            "mediaId": imdb_id,
        }

        try:
            client = await self._get_likes_client()
            result = await client.get(url, params=params)
            result.raise_for_status()
            status = result.json().get("status", "")
            if status and status.lower() == "loved":
                return True
            else:
                return False
        except Exception as e:
            logger.error(
                f"Error checking if user has loved a movie or series: {e}",
                exc_info=True,
            )
            return False

    async def get_library_items(self) -> Dict[str, List[Dict]]:
        """
        Fetch library items from Stremio once and return both watched and loved items.
        Returns a dict with 'watched' and 'loved' keys.
        """
        if not self._auth_key and (not self.username or not self.password):
            logger.warning("Stremio credentials not configured")
            return {"watched": [], "loved": []}

        try:
            # Get auth token
            auth_key = await self.get_auth_key()
            if not auth_key:
                logger.error("Failed to get Stremio auth token")
                return {"watched": [], "loved": []}

            # Fetch library items once
            url = f"{self.base_url}/api/datastoreGet"
            payload = {
                "authKey": auth_key,
                "collection": "libraryItem",
                "all": True,
            }

            client = await self._get_client()
            result = await client.post(url, json=payload)
            result.raise_for_status()
            items = result.json().get("result", [])
            logger.info(f"Fetched {len(items)} library items from Stremio")

            # Filter only items that user has watched
            watched_items = [
                item
                for item in items
                if (
                    item.get("state", {}).get("timesWatched", 0) > 0
                    and item.get("type") in ["movie", "series"]
                    and item.get("_id").startswith("tt")
                )
            ]
            logger.info(f"Filtered {len(watched_items)} watched library items")

            # Check if user has loved the movie or series in parallel
            loved_statuses = await asyncio.gather(
                *[
                    self.is_loved(auth_key, item.get("_id"), item.get("type"))
                    for item in watched_items
                ]
            )

            # Separate loved and watched items
            loved_items = [
                item for item, loved in zip(watched_items, loved_statuses) if loved
            ]
            logger.info(f"Found {len(loved_items)} loved library items")

            # Format watched items
            formatted_watched = []
            for item in watched_items:
                formatted_watched.append(
                    {
                        "type": item.get("type"),
                        "_id": item.get("_id"),
                        "_mtime": item.get("_mtime", ""),
                        "name": item.get("name"),
                    }
                )

            # Format and sort loved items
            formatted_loved = []
            for item in loved_items:
                formatted_loved.append(
                    {
                        "type": item.get("type"),
                        "_id": item.get("_id"),
                        "_mtime": item.get("_mtime", ""),
                        "name": item.get("name"),
                    }
                )

            # Sort loved items by modification time (most recent first)
            formatted_loved.sort(key=lambda x: x.get("_mtime", ""), reverse=True)

            return {"watched": formatted_watched, "loved": formatted_loved}
        except Exception as e:
            logger.error(f"Error fetching library items: {e}", exc_info=True)
            return {"watched": [], "loved": []}

    async def get_addons(self, auth_key: str | None = None) -> list[dict]:
        """Get addons from Stremio."""
        url = f"{self.base_url}/api/addonCollectionGet"
        payload = {
            "type": "AddonCollectionGet",
            "authKey": auth_key or await self.get_auth_key(),
            "update": True,
        }
        client = await self._get_client()
        result = await client.post(url, json=payload)
        result.raise_for_status()
        data = result.json()
        error_payload = data.get("error")
        if not error_payload and (data.get("code") and data.get("message")):
            error_payload = data

        if error_payload:
            message = "Invalid Stremio auth key."
            if isinstance(error_payload, dict):
                message = error_payload.get("message") or message
            elif isinstance(error_payload, str):
                message = error_payload or message
            logger.warning("Addon collection request failed: {}", error_payload)
            raise ValueError(f"Stremio: {message}")
        addons = data.get("result", {}).get("addons", [])
        logger.info(f"Found {len(addons)} addons")
        return addons

    async def update_addon(self, addons: list[dict], auth_key: str | None = None):
        """Update an addon in Stremio."""
        url = f"{self.base_url}/api/addonCollectionSet"
        payload = {
            "type": "AddonCollectionSet",
            "authKey": auth_key or await self.get_auth_key(),
            "addons": addons,
        }

        client = await self._get_client()
        result = await client.post(url, json=payload)
        result.raise_for_status()
        logger.info(f"Updated addons")
        return result.json().get("result", {}).get("success", False)

    async def update_catalogs(self, catalogs: list[dict], auth_key: str | None = None):
        auth_key = auth_key or await self.get_auth_key()
        addons = await self.get_addons(auth_key)
        catalogs = BASE_CATALOGS + catalogs
        logger.info(f"Found {len(addons)} addons")
        # find addon with id "com.watchly"
        for addon in addons:
            if addon.get("manifest", {}).get("id") == settings.ADDON_ID:
                logger.info(f"Found addon with id {settings.ADDON_ID}")
                addon["manifest"]["catalogs"] = catalogs
                break
        return await self.update_addon(addons, auth_key)
