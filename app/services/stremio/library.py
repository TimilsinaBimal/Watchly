import asyncio
import time

from loguru import logger

from .client import StremioClient


class LibraryManager:
    """Handles fetching and caching of user library."""

    def __init__(self, client: StremioClient):
        self.client = client
        # Simple in-memory cache for the instance lifetime
        self._cache = {}

    async def _fetch_likes(self, auth_key: str) -> list:
        """Fetch likes from likes.strem.io."""
        url = "https://likes.strem.io/api/getLikes"
        try:
            data = await self.client.get_with_retries(url, params={"authKey": auth_key})
            return data.get("result", []) if isinstance(data, dict) else []
        except Exception:
            return []

    async def get_library_items(self, auth_key: str, use_cache: bool = True, ttl_s: int = 600) -> dict:
        now = time.time()
        # Check instance memory cache first
        if use_cache:
            if cached := self._cache.get(auth_key):
                if now < cached["expiry"]:
                    return cached["data"]

        # 1. Fetch Datastore (Library)
        url = f"{self.client.base_url}/api/datastoreGet"
        payload = {"authKey": auth_key, "collection": "libraryItem", "all": True}

        # 2. Fetch Likes
        likes_task = asyncio.create_task(self._fetch_likes(auth_key))

        try:
            data = await self.client.post_with_retries(url, payload)
            library_items_raw = data.get("result", [])
            likes_raw = await likes_task

            # Map likes for faster lookup
            liked_ids = {like.get("_id") for like in likes_raw if like.get("_id")}

            watched = []
            added = []
            loved = []
            in_progress = []

            for item in library_items_raw:
                itype = item.get("type")
                if itype == "tv":
                    itype = "series"  # Standardize early
                if itype not in ("movie", "series"):
                    continue

                iid = item.get("_id", "")
                if not iid.startswith("tt"):
                    continue

                state = item.get("state") or {}

                # Fetch state metrics
                times = state.get("timesWatched", 0)
                flagged = state.get("flaggedWatched", 0)
                duration = state.get("duration") or 0
                time_watched = state.get("timeWatched", 0)

                # Check for completion via time/duration (safe div)
                completion = 0
                if duration > 0:
                    completion = time_watched / duration

                is_watched = (times > 0) or (flagged > 0) or (completion > 0.7)

                # Enhanced flags for ScoringService
                in_likes = iid in liked_ids
                is_loved = flagged > 0 or in_likes
                is_liked = times > 1 or in_likes or (not item.get("removed") and not item.get("temp"))

                mini_item = {
                    "_id": iid,
                    "type": itype,
                    "name": item.get("name", ""),
                    "_mtime": item.get("_mtime"),
                    "temp": item.get("temp", False),
                    "removed": item.get("removed", False),
                    "state": state,
                    "_is_loved": is_loved,
                    "_is_liked": is_liked,
                }

                if not item.get("removed"):
                    if is_watched:
                        watched.append(mini_item)
                        if is_loved or times > 1:
                            loved.append(mini_item)
                    else:
                        if completion > 0:
                            in_progress.append(mini_item)
                        added.append(mini_item)

            # 3. Add Likes that are NOT in library to 'loved' (or just use them for profile building)
            # This ensures even if a liked movie isn't in Stremio library, we know about it.
            # (Optional: implementation depends on how thorough we want to be)

            logger.info(
                f"Library: {len(library_items_raw)} fetched, {len(likes_raw)} likes found. "
                f"Summary: {len(watched)} watched, {len(loved)} loved, {len(in_progress)} in_progress"
            )
            result = {
                "watched": watched,
                "added": added,
                "loved": loved,
                "in_progress": in_progress,
                "removed": [],
                "likes_raw": likes_raw,  # Optional: passing through for depth
            }

            # Update memory cache
            self._cache[auth_key] = {"data": result, "expiry": now + ttl_s}

            return result
        except Exception as e:
            logger.error(f"Failed to fetch library: {e}")
            return {"watched": [], "added": []}
