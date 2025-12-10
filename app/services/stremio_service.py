import asyncio
from urllib.parse import urlparse

import httpx
from async_lru import alru_cache
from loguru import logger

from app.core.config import settings

BASE_CATALOGS = [
    {"type": "movie", "id": "watchly.rec", "name": "Top Picks for You", "extra": []},
    {"type": "series", "id": "watchly.rec", "name": "Top Picks for You", "extra": []},
]


def match_hostname(url: str, hostname: str) -> bool:
    """
    Checks if the hostname extracted from a URL matches a given hostname string.
    """
    parsed_url = urlparse(url)
    return parsed_url.hostname == hostname


class StremioService:
    """Service for interacting with Stremio API to fetch user library."""

    def __init__(
        self,
        username: str = "",
        password: str = "",
        auth_key: str | None = None,
    ):
        self.base_url = "https://api.strem.io"
        self.username = username
        self.password = password
        self._auth_key: str | None = auth_key
        if not self._auth_key and (not self.username or not self.password):
            raise ValueError("Username/password or auth key are required")
        # Reuse HTTP client for connection pooling and better performance
        self._client: httpx.AsyncClient | None = None
        self._likes_client: httpx.AsyncClient | None = None

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
        """Return the cached auth key."""
        if not self._auth_key:
            raise ValueError("Stremio auth key is missing.")
        return self._auth_key

    async def is_loved(self, auth_key: str, imdb_id: str, media_type: str) -> tuple[bool, bool]:
        """
        Check if user has loved or liked a movie or series.
        Returns: (is_loved, is_liked)
        """
        if not imdb_id.startswith("tt"):
            return False, False
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
            return (status == "loved", status == "liked")
        except Exception as e:
            logger.error(
                f"Error checking if user has loved a movie or series: {e}",
                exc_info=True,
            )
            return False, False

    @alru_cache(maxsize=1000, ttl=3600)
    async def get_loved_items(self, auth_token: str, media_type: str) -> list[dict]:
        async with httpx.AsyncClient() as client:
            url = f"https://likes.stremio.com/addons/loved/movies-shows/{auth_token}/catalog/{media_type}/stremio-loved-{media_type.lower()}.json"  # noqa: E501
            response = await client.get(url)
            response.raise_for_status()
            metas = response.json().get("metas", [])
            return [meta.get("id") for meta in metas]

    @alru_cache(maxsize=1000, ttl=3600)
    async def get_liked_items(self, auth_token: str, media_type: str) -> list[dict]:
        async with httpx.AsyncClient() as client:
            url = f"https://likes.stremio.com/addons/liked/movies-shows/{auth_token}/catalog/{media_type}/stremio-liked-{media_type.lower()}.json"  # noqa: E501
            response = await client.get(url)
            response.raise_for_status()
            metas = response.json().get("metas", [])
            return [meta.get("id") for meta in metas]

    async def get_user_info(self) -> dict[str, str]:
        """Fetch user ID and email using the auth key."""
        if not self._auth_key:
            raise ValueError("Stremio auth key is missing.")

        url = f"{self.base_url}/api/getUser"
        payload = {
            "type": "GetUser",
            "authKey": self._auth_key,
        }

        try:
            client = await self._get_client()
            result = await client.post(url, json=payload)
            result.raise_for_status()
            data = result.json()

            if "error" in data:
                error_msg = data["error"]
                if isinstance(error_msg, dict):
                    error_msg = error_msg.get("message", "Unknown error")
                raise ValueError(f"Stremio Error: {error_msg}")

            # Structure: { result: { _id, email, ... } }
            res = data.get("result", {})
            user_id = res.get("_id", "")
            email = res.get("email", "")

            if not user_id:
                raise ValueError("Could not retrieve user ID from Stremio profile.")

            return {"user_id": user_id, "email": email}
        except Exception as e:
            logger.error(f"Error fetching user profile: {e}")
            raise

    async def get_user_email(self) -> str:
        """Fetch user email using the auth key."""
        user_info = await self.get_user_info()
        return user_info.get("email", "")

    async def get_library_items(self) -> dict[str, list[dict]]:
        """
        Fetch library items from Stremio once and return both watched and loved items.
        Returns a dict with 'watched' and 'loved' keys.
        """
        if not self._auth_key:
            logger.warning("Stremio auth key not configured")
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

            # Sort watched items by watched time (most recent first)
            watched_items.sort(key=lambda x: x.get("state", {}).get("lastWatched", ""), reverse=True)

            loved_items = []

            # fetch loved and liked items

            loved_movies, loved_series, liked_movies, liked_series = await asyncio.gather(
                self.get_loved_items(auth_key, "movie"),
                self.get_loved_items(auth_key, "series"),
                self.get_liked_items(auth_key, "movie"),
                self.get_liked_items(auth_key, "series"),
            )

            for item in watched_items:
                loved = False
                if item.get("_id") in loved_movies or item.get("_id") in loved_series:
                    item["_is_loved"] = True
                    loved = True
                if item.get("_id") in liked_movies or item.get("_id") in liked_series:
                    item["_is_liked"] = True
                    loved = True

                if loved:
                    loved_items.append(item)

            logger.info(f"Found {len(loved_items)} loved library items")

            # Return raw items; ScoringService will handle Pydantic conversion
            return {"watched": watched_items, "loved": loved_items}
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
            logger.warning(f"Addon collection request failed: {error_payload}")
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
        logger.info("Updated addons")
        return result.json().get("result", {}).get("success", False)

    async def update_catalogs(self, catalogs: list[dict], auth_key: str | None = None):
        auth_key = auth_key or await self.get_auth_key()
        addons = await self.get_addons(auth_key)
        catalogs = BASE_CATALOGS + catalogs
        logger.info(f"Found {len(addons)} addons")
        # find addon with id "com.watchly"
        for addon in addons:
            if addon.get("manifest", {}).get("id") == settings.ADDON_ID and match_hostname(
                addon.get("transportUrl"), settings.HOST_NAME
            ):
                logger.info(f"Found addon with id {settings.ADDON_ID}")
                addon["manifest"]["catalogs"] = catalogs
                break
        return await self.update_addon(addons, auth_key)

    async def is_addon_installed(self, auth_key: str | None = None):
        auth_key = auth_key or await self.get_auth_key()
        addons = await self.get_addons(auth_key)
        for addon in addons:
            if addon.get("manifest", {}).get("id") == settings.ADDON_ID and match_hostname(
                addon.get("transportUrl"), settings.HOST_NAME
            ):
                return True
        return False
