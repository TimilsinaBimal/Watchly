import asyncio
from typing import Any

from async_lru import alru_cache
from loguru import logger

from app.services.stremio.client import StremioClient, StremioLikesClient


class StremioLibraryService:
    """
    Handles fetching and processing of user's Stremio library and likes.
    """

    def __init__(self, client: StremioClient, likes_client: StremioLikesClient):
        self.client = client
        self.likes_client = likes_client

    @alru_cache(maxsize=100, ttl=3600)
    async def get_likes_by_type(self, auth_token: str, media_type: str, status: str = "loved") -> list[str]:
        """
        Fetch IDs of items liked or loved by the user.
        status: 'loved' or 'liked'
        """
        path = f"/addons/{status}/movies-shows/{auth_token}/catalog/{media_type}/stremio-{status}-{media_type}.json"
        try:
            data = await self.likes_client.get(path)
            metas = data.get("metas", [])
            return [meta.get("id") for meta in metas if meta.get("id")]
        except Exception as e:
            logger.exception(f"Failed to fetch {status} {media_type} items: {e}")
            return []

    async def get_library_items(self, auth_key: str) -> dict[str, list[dict[str, Any]]]:
        """
        Fetch all library items and categorize them (watched, loved, added, removed).
        """
        try:
            # 1. Fetch raw library from datastore
            payload = {
                "authKey": auth_key,
                "collection": "libraryItem",
                "all": True,
            }
            data = await self.client.post("/api/datastoreGet", json=payload)
            all_raw_items = data.get("result", [])

            # 2. Fetch loved/liked IDs in parallel
            loved_movies_task = self.get_likes_by_type(auth_key, "movie", "loved")
            loved_series_task = self.get_likes_by_type(auth_key, "series", "loved")
            liked_movies_task = self.get_likes_by_type(auth_key, "movie", "liked")
            liked_series_task = self.get_likes_by_type(auth_key, "series", "liked")

            loved_movies, loved_series, liked_movies, liked_series = await asyncio.gather(
                loved_movies_task, loved_series_task, liked_movies_task, liked_series_task
            )

            logger.info(
                f"Found {len(loved_movies)} loved movies, {len(loved_series)} loved series,"
                f" {len(liked_movies)} liked movies, {len(liked_series)} liked series"
            )

            # all_loved_ids = set(loved_movies + loved_series + liked_movies + liked_series)

            # 3. Categorize items
            watched: list[dict] = []
            loved: list[dict] = []
            added: list[dict] = []
            removed: list[dict] = []
            liked: list[dict] = []

            # Create sets for faster lookup
            loved_set = set(loved_movies + loved_series)
            liked_set = set(liked_movies + liked_series)
            # all_loved_ids = loved_set.union(liked_set)

            for item in all_raw_items:
                # Basic validation
                if item.get("type") not in ["movie", "series"]:
                    continue
                item_id = item.get("_id", "")
                if not item_id.startswith("tt") and not item_id.startswith("tmdb:"):
                    # either imdb id or tmdb id should be there.
                    continue

                # Check Watched status
                state = item.get("state", {}) or {}
                times_watched = int(state.get("timesWatched") or 0)
                flagged_watched = int(state.get("flaggedWatched") or 0)
                duration = int(state.get("duration") or 0)
                time_watched = int(state.get("timeWatched") or 0)

                is_completion_high = duration > 0 and (time_watched / duration) >= 0.7
                is_watched = times_watched > 0 or flagged_watched > 0 or is_completion_high

                # if item is loved or liked and but not watched, then also we need to add it
                # as users might not have watched it in stremio itself.
                if item_id in loved_set:
                    item["_is_loved"] = True
                    loved.append(item)

                elif item_id in liked_set:
                    item["_is_liked"] = True
                    liked.append(item)

                elif is_watched:
                    watched.append(item)

                elif not item.get("removed") and not item.get("temp"):
                    # item has not removed and item is not temporary meaning item is not
                    # added by stremio itself on user watch
                    added.append(item)
                else:
                    continue
                # elif item.get("removed"):
                #     # do not do anything with removed items
                #     # removed.append(item)
                #     continue

            # 4. Sort watched items by recency
            def sort_by_recency(x: dict):
                state = x.get("state", {}) or {}
                return (str(state.get("lastWatched") or str(x.get("_mtime") or "")), x.get("_mtime") or "")

            watched.sort(key=sort_by_recency, reverse=True)
            loved.sort(key=sort_by_recency, reverse=True)
            liked.sort(key=sort_by_recency, reverse=True)
            added.sort(key=sort_by_recency, reverse=True)
            removed.sort(key=sort_by_recency, reverse=True)

            logger.info(
                f"Processed {len(watched)} watched items, {len(loved)} loved items,"
                f"{len(liked)} liked items, {len(added)} added items, {len(removed)} removed items"
            )

            return {
                "watched": watched,
                "loved": loved,
                "liked": liked,
                "added": added,
                "removed": removed,
            }
        except Exception as e:
            logger.exception(f"Error processing library items: {e}")
            return {"watched": [], "loved": [], "liked": [], "added": [], "removed": []}
