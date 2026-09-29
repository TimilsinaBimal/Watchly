import asyncio
from typing import Any

import httpx
from loguru import logger

from app.core.base_client import BaseClient
from app.models.history import WatchHistory, WatchHistoryItem
from app.models.library import LibraryCollection, StremioLibraryItem, StremioState


def stremio_library_to_watch_history(library: LibraryCollection) -> WatchHistory:
    """Convert typed LibraryCollection to unified WatchHistory format."""
    items: list[WatchHistoryItem] = []
    seen: set[str] = set()

    category_items = [
        (library.loved, True, False),
        (library.liked, False, True),
        (library.watched, False, False),
        (library.added, False, False),
    ]

    for lib_items, is_loved, is_liked in category_items:
        for item in lib_items:
            imdb_id = item.id
            if not imdb_id.startswith("tt") or imdb_id in seen:
                continue
            seen.add(imdb_id)

            state = item.state
            duration = state.duration
            time_watched = state.timeWatched
            times_watched = state.timesWatched
            flagged_watched = state.flaggedWatched

            if flagged_watched > 0 or times_watched > 0:
                completion = 1.0
            elif duration > 0:
                completion = min(time_watched / duration, 1.0)
            else:
                completion = 0.0

            rating: float | None = None
            if is_loved or item.is_loved:
                rating = 9.0
            elif is_liked or item.is_liked:
                rating = 7.0

            items.append(
                WatchHistoryItem(
                    imdb_id=imdb_id,
                    type=item.type,
                    name=item.name,
                    rating=rating,
                    watch_count=max(times_watched, 1) if completion > 0 else 0,
                    completion=completion,
                    last_watched=item.last_interaction,
                )
            )

    return WatchHistory(items=items, source="stremio")


# Stand-in runtime for external items, which report completion as a fraction with
# no duration attached. Only the timeWatched/duration ratio is ever read, so the
# value is arbitrary — it just has to be large enough that int() rounding doesn't
# bite.
_COMPLETION_DURATION_PROXY = 6000


def watch_history_item_to_library_item(item: WatchHistoryItem, is_loved: bool, is_liked: bool) -> StremioLibraryItem:
    """Convert one external history item into the library shape the scorer reads.

    Completion is written as a timeWatched/duration ratio rather than via the
    flaggedWatched flag, because ScoringService skips its rewatch bonus outright
    when that flag is set — flagging a completed item would cost it the rewatch
    credit its watch_count earned.
    """
    completion = min(max(item.completion, 0.0), 1.0)
    state = StremioState(
        lastWatched=item.last_watched,
        duration=_COMPLETION_DURATION_PROXY,
        timeWatched=int(_COMPLETION_DURATION_PROXY * completion),
        timesWatched=max(item.watch_count, 0),
    )

    return StremioLibraryItem(
        _id=item.imdb_id,
        type=item.type,
        name=item.name,
        state=state,
        temp=False,
        removed=False,
        _is_loved=is_loved,
        _is_liked=is_liked,
    )


def watch_history_to_library_collection(history: WatchHistory) -> LibraryCollection:
    """Convert an external WatchHistory (Trakt/Simkl) into a LibraryCollection.

    Bucketing rules:
      loved:   rating >= 9, OR no rating + watch_count >= 2 (rewatch as love proxy)
      liked:   7 <= rating < 9
      watched: everything else with any completion/watch signal

    Items without IMDb IDs are skipped — downstream code keys on `tt…` / `tmdb:…`
    everywhere and dropping them up front avoids fanning empty IDs into TMDB lookups.
    """
    loved: list[StremioLibraryItem] = []
    liked: list[StremioLibraryItem] = []
    watched: list[StremioLibraryItem] = []
    seen: set[str] = set()

    for item in history.items:
        if not item.imdb_id or item.imdb_id in seen:
            continue
        seen.add(item.imdb_id)

        r = item.rating
        is_loved = (r is not None and r >= 9.0) or (r is None and item.watch_count >= 2)
        is_liked = not is_loved and r is not None and r >= 7.0
        lib_item = watch_history_item_to_library_item(item, is_loved, is_liked)

        if is_loved:
            loved.append(lib_item)
        elif is_liked:
            liked.append(lib_item)
        else:
            watched.append(lib_item)

    return LibraryCollection(loved=loved, liked=liked, watched=watched, source=history.source)


class StremioLibraryService:
    def __init__(self, client: BaseClient, likes_client: BaseClient):
        self.client = client
        self.likes_client = likes_client

    async def get_likes_by_type(self, auth_token: str, media_type: str, status: str) -> list[dict[str, Any]]:
        """Full metadata of the items the user marked `status` ('loved' or 'liked')."""
        path = f"/addons/{status}/movies-shows/{{token}}/catalog/{media_type}/stremio-{status}-{media_type}.json"
        # The auth token sits in the path; log the template, not the key.
        data = await self.likes_client.get(path.format(token=auth_token), log_url=path)
        metas = data.get("metas", [])
        return [meta for meta in metas if meta.get("id")]

    async def get_library_items(self, auth_key: str) -> LibraryCollection | None:
        """
        Fetch all library items and categorize them (watched, loved, added, removed).

        Returns None when the library can't be fetched, so callers can tell a failure
        apart from an empty library and keep what they have cached.
        """
        try:
            payload = {
                "authKey": auth_key,
                "collection": "libraryItem",
                "all": True,
            }
            data = await self.client.post("/api/datastoreGet", json=payload)
            # Stremio reports a rejected authKey in a 200 body, and the client turns an
            # empty or non-JSON body into {}. Neither is a library.
            if "error" in data or "result" not in data:
                logger.warning(f"Stremio datastoreGet returned no library: {data.get('error')}")
                return None
            all_raw_items = data["result"]

            loved_movies_task = self.get_likes_by_type(auth_key, "movie", "loved")
            loved_series_task = self.get_likes_by_type(auth_key, "series", "loved")
            liked_movies_task = self.get_likes_by_type(auth_key, "movie", "liked")
            liked_series_task = self.get_likes_by_type(auth_key, "series", "liked")

            (
                loved_movies,
                loved_series,
                liked_movies,
                liked_series,
            ) = await asyncio.gather(
                loved_movies_task,
                loved_series_task,
                liked_movies_task,
                liked_series_task,
            )

            logger.info(
                f"Found {len(loved_movies)} loved movies, {len(loved_series)} loved series,"
                f" {len(liked_movies)} liked movies, {len(liked_series)} liked series"
            )

            loved_set = {item.get("id") for item in (loved_movies + loved_series) if item.get("id")}
            liked_set = {item.get("id") for item in (liked_movies + liked_series) if item.get("id")}

            existing_library_ids = {item.get("_id") for item in all_raw_items if item.get("_id")}

            # Items loved/liked elsewhere but never watched or added still count.
            for source_items, is_loved in [
                (loved_movies + loved_series, True),
                (liked_movies + liked_series, False),
            ]:
                for item in source_items:
                    item_id = item.get("id")
                    if item_id and item_id not in existing_library_ids:
                        virtual_item = {
                            "_id": item_id,
                            "name": item.get("name", ""),
                            "type": item.get("type", "movie"),
                            "poster": item.get("poster"),
                            "background": item.get("background"),
                            "logo": item.get("logo"),
                            "year": item.get("year"),
                            "removed": False,
                            "temp": False,
                            # Important: Mark as loved/liked so the next loop categorizes it correctly
                            "_is_loved": is_loved,
                            "_is_liked": not is_loved,
                            # Populate state to indicate item has been watched (as implied by love/like)
                            "state": {
                                "timesWatched": 1,
                                "flaggedWatched": 1,
                            },
                            "_source": "likes_api",  # Marker for debugging
                        }
                        all_raw_items.append(virtual_item)
                        existing_library_ids.add(item_id)

            watched: list[StremioLibraryItem] = []
            loved: list[StremioLibraryItem] = []
            added: list[StremioLibraryItem] = []
            liked: list[StremioLibraryItem] = []

            for item in all_raw_items:
                if item.get("type") not in ["movie", "series"]:
                    continue
                item_id = item.get("_id", "")
                # Downstream history/profile pipeline assumes IMDb ids; tmdb-only
                # items can't be converted and would be silently dropped later.
                if not item_id.startswith("tt"):
                    continue

                state = item.get("state", {}) or {}
                times_watched = int(state.get("timesWatched") or 0)
                flagged_watched = int(state.get("flaggedWatched") or 0)
                duration = int(state.get("duration") or 0)
                time_watched = int(state.get("timeWatched") or 0)

                is_completion_high = duration > 0 and (time_watched / duration) >= 0.7
                is_watched = times_watched > 0 or flagged_watched > 0 or is_completion_high

                if item_id in loved_set:
                    item["_is_loved"] = True
                elif item_id in liked_set:
                    item["_is_liked"] = True

                try:
                    typed_item = StremioLibraryItem(**item)
                except Exception:
                    continue

                if item_id in loved_set:
                    loved.append(typed_item)
                elif item_id in liked_set:
                    liked.append(typed_item)
                elif is_watched:
                    watched.append(typed_item)
                elif not item.get("removed") and not item.get("temp"):
                    added.append(typed_item)
                else:
                    continue

            def sort_by_recency(x: StremioLibraryItem):
                return (
                    str(x.state.lastWatched or x.mtime or ""),
                    x.mtime or "",
                )

            watched.sort(key=sort_by_recency, reverse=True)
            loved.sort(key=sort_by_recency, reverse=True)
            liked.sort(key=sort_by_recency, reverse=True)
            added.sort(key=sort_by_recency, reverse=True)

            logger.info(
                f"Found {len(all_raw_items)} library items. Processed {len(watched)} watched items,"
                f" {len(loved)} loved items,{len(liked)} liked items, {len(added)} added items"
            )

            return LibraryCollection(
                watched=watched,
                loved=loved,
                liked=liked,
                added=added,
                source="stremio",
            )
        except httpx.HTTPError:
            # BaseClient has already logged the request that failed.
            return None
        except Exception:
            logger.exception("Error processing library items")
            return None
