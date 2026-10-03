import asyncio
from datetime import datetime
from typing import Any

from loguru import logger

from app.core.base_client import BaseClient
from app.models.history import WatchHistory, WatchHistoryItem

# MDBList's maximum page size, so this is the fewest requests possible.
HISTORY_PAGE_LIMIT = 1000
# Backstop against a pagination contract change turning the loop endless.
MAX_HISTORY_PAGES = 50


class MDBListService:
    """MDBList sync API, authenticated with the user's own API key.

    The key travels as a query parameter, so callers must never log an exception
    from this service with `str(e)`: the httpx message carries the full URL.
    """

    BASE_URL = "https://api.mdblist.com"

    def __init__(self):
        self.client = BaseClient(base_url=self.BASE_URL, timeout=15.0, max_retries=3)

    async def close(self) -> None:
        await self.client.close()

    async def get_user(self, api_key: str) -> dict[str, Any]:
        return await self.client.get("/user", params={"apikey": api_key})

    async def _get_all_pages(self, url: str, api_key: str) -> dict[str, list[dict[str, Any]]]:
        """Every page of a sync endpoint, as {"movies": [...], "shows": [...]}.

        Pages follow `pagination.next_cursor`; the page size is MDBList's maximum so
        most libraries fit in one request.
        """
        merged: dict[str, list[dict[str, Any]]] = {"movies": [], "shows": []}
        params: dict[str, Any] = {"apikey": api_key, "limit": HISTORY_PAGE_LIMIT}
        for _ in range(MAX_HISTORY_PAGES):
            data = await self.client.get(url, params=params)
            for key in merged:
                merged[key].extend(data.get(key) or [])
            cursor = (data.get("pagination") or {}).get("next_cursor")
            if not cursor:
                return merged
            params["cursor"] = cursor

        logger.warning(f"MDBList {url}: stopped at the {MAX_HISTORY_PAGES}-page cap")
        return merged

    async def get_history(self, api_key: str) -> WatchHistory:
        # A failed endpoint raises rather than degrading to an empty list: an empty
        # history looks like a user who has watched nothing, and the callers cache it
        # as the user's library.
        watched, rated = await asyncio.gather(
            self._get_all_pages("/sync/watched", api_key),
            self._get_all_pages("/sync/ratings", api_key),
        )

        ratings: dict[str, float] = {}
        for entry in rated["movies"] + rated["shows"]:
            imdb_id = self._imdb_id(entry)
            if imdb_id and entry.get("rating"):
                ratings[imdb_id] = float(entry["rating"])

        items: list[WatchHistoryItem] = []
        seen: set[str] = set()
        for mtype, key in (("movie", "movies"), ("series", "shows")):
            for entry in watched[key]:
                imdb_id = self._imdb_id(entry)
                if not imdb_id or imdb_id in seen:
                    continue
                seen.add(imdb_id)
                items.append(
                    WatchHistoryItem(
                        imdb_id=imdb_id,
                        type=mtype,
                        name=self._media(entry).get("title", ""),
                        rating=ratings.get(imdb_id),
                        # MDBList reports plays only as one row per play; a rewatch
                        # signal would cost a second full fetch, so ratings carry
                        # loved/liked here, as they do for Simkl shows.
                        watch_count=1,
                        completion=1.0,
                        last_watched=self._parse_date(entry.get("last_watched_at") or entry.get("watched_at")),
                        source="mdblist",
                    )
                )

        # Rated but never marked watched still says something about taste.
        for mtype, key in (("movie", "movies"), ("series", "shows")):
            for entry in rated[key]:
                imdb_id = self._imdb_id(entry)
                if not imdb_id or imdb_id in seen or not entry.get("rating"):
                    continue
                seen.add(imdb_id)
                items.append(
                    WatchHistoryItem(
                        imdb_id=imdb_id,
                        type=mtype,
                        name=self._media(entry).get("title", ""),
                        rating=float(entry["rating"]),
                        watch_count=0,
                        completion=0.0,
                        last_watched=self._parse_date(entry.get("rated_at")),
                        source="mdblist",
                    )
                )

        logger.info(f"MDBList history: {len(items)} items ({len(ratings)} rated)")
        return WatchHistory(items=items, source="mdblist")

    @staticmethod
    def _media(entry: dict[str, Any]) -> dict[str, Any]:
        return entry.get("movie") or entry.get("show") or {}

    @classmethod
    def _imdb_id(cls, entry: dict[str, Any]) -> str | None:
        return (cls._media(entry).get("ids") or {}).get("imdb")

    @staticmethod
    def _parse_date(date_str: str | None) -> datetime | None:
        if not date_str:
            return None
        try:
            return datetime.fromisoformat(str(date_str).replace("Z", "+00:00"))
        except ValueError:
            return None


mdblist_service = MDBListService()
