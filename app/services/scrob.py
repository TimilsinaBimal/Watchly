import asyncio
import hashlib
from datetime import datetime
from typing import TYPE_CHECKING, Any

from loguru import logger

from app.core.base_client import BaseClient
from app.core.constants import DEFAULT_CONCURRENCY_LIMIT
from app.models.history import WatchHistory, WatchHistoryItem

if TYPE_CHECKING:
    from app.services.tmdb.service import TMDBService

# Scrob's documented maximum page size, so this is the fewest requests possible.
HISTORY_PAGE_SIZE = 100
# Backstop against a pagination contract change turning the loop endless.
MAX_HISTORY_PAGES = 100


class ScrobService:
    """Scrob's REST API, authorized with the per-user API key.

    Every user runs their own instance, so the base URL is a credential like
    the key: each call builds a short-lived client against it. The key travels
    in the X-Api-Key header, never in the URL.
    """

    @staticmethod
    def _client(base_url: str) -> BaseClient:
        return BaseClient(base_url=base_url.rstrip("/"), timeout=20.0, max_retries=3)

    @staticmethod
    def _headers(api_key: str) -> dict[str, str]:
        return {"X-Api-Key": api_key}

    async def probe(self, base_url: str, api_key: str) -> None:
        """Cheapest authenticated call; raises when the instance is unreachable
        or rejects the key."""
        client = self._client(base_url)
        try:
            await client.get("/history", params={"page": 1, "page_size": 1}, headers=self._headers(api_key))
        finally:
            await client.close()

    async def get_history(self, base_url: str, api_key: str, tmdb_service: "TMDBService") -> WatchHistory:
        """Watched movies and shows of one Scrob account, keyed on IMDb ids.

        A failed endpoint raises rather than degrading to an empty list: an empty
        history looks like a user who has watched nothing, and the callers cache it
        as the user's library. Episodes collapse into their show, so a series
        counts once however many episodes were played.
        """
        client = self._client(base_url)
        try:
            events, ratings = await asyncio.gather(
                self._get_all_events(client, api_key),
                client.get("/ratings", headers=self._headers(api_key)),
            )
        finally:
            await client.close()

        items: dict[str, WatchHistoryItem] = {}
        for event in events:
            media = event.get("media") or {}
            if media.get("type") == "movie":
                self._merge(items, self._movie_key(media), "movie", media.get("title"), event.get("watched_at"))
            elif media.get("type") == "episode":
                # The show, not the episode: a series item with the episode's
                # own id would fan one show into hundreds of library entries.
                key = f"tmdb:{media.get('show_tmdb_id')}" if media.get("show_tmdb_id") else None
                self._merge(items, key, "series", media.get("show_title"), event.get("watched_at"))

        for rating in (ratings.get("results") or []) if isinstance(ratings, dict) else []:
            media = rating.get("media") or {}
            # Season and episode ratings score at a level Watchly doesn't model;
            # only title-level ratings reach the profile.
            if media.get("type") == "movie":
                key = self._movie_key(media)
                mtype, name = "movie", media.get("title")
            elif media.get("type") == "show" and rating.get("season_number") is None:
                key = f"tmdb:{media.get('tmdb_id')}" if media.get("tmdb_id") else None
                mtype, name = "series", media.get("title")
            else:
                continue
            if not key:
                continue
            item = items.get(key)
            if item is None:
                items[key] = WatchHistoryItem(
                    imdb_id=key,
                    type=mtype,
                    name=str(name or ""),
                    rating=float(rating["rating"]),
                    watch_count=0,
                    completion=0.0,
                    last_watched=self._parse_date(rating.get("rated_at")),
                    source="scrob",
                )
            elif item.rating is None:
                item.rating = float(rating["rating"])

        resolved = await self._resolve_imdb_ids(items, tmdb_service)
        logger.info(f"Scrob history: {len(resolved)} items ({len(ratings.get('results') or [])} rated rows)")
        return WatchHistory(items=resolved, source="scrob")

    async def _get_all_events(self, client: BaseClient, api_key: str) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for page in range(1, MAX_HISTORY_PAGES + 1):
            data = await client.get(
                "/history", params={"page": page, "page_size": HISTORY_PAGE_SIZE}, headers=self._headers(api_key)
            )
            events.extend(data.get("results") or [])
            if page >= int(data.get("total_pages") or 1):
                return events

        logger.warning(f"Scrob /history: stopped at the {MAX_HISTORY_PAGES}-page cap")
        return events

    @staticmethod
    def _movie_key(media: dict[str, Any]) -> str | None:
        if media.get("imdb_id"):
            return str(media["imdb_id"])
        if media.get("tmdb_id"):
            return f"tmdb:{media['tmdb_id']}"
        return None

    @staticmethod
    def _merge(items: dict[str, WatchHistoryItem], key: str | None, mtype: str, name: Any, watched_at: Any) -> None:
        if not key:
            return
        last_watched = ScrobService._parse_date(watched_at)
        existing = items.get(key)
        if existing is None:
            items[key] = WatchHistoryItem(
                imdb_id=key,
                type=mtype,
                name=str(name or ""),
                last_watched=last_watched,
                source="scrob",
            )
            return
        # A rewatched movie keeps its rewatch signal; a series stays one watch
        # however many of its episodes were played, or every long show would
        # land in "loved" through the watch_count rewatch proxy.
        if mtype == "movie":
            existing.watch_count += 1
        if last_watched and (existing.last_watched is None or last_watched > existing.last_watched):
            existing.last_watched = last_watched

    @staticmethod
    async def _resolve_imdb_ids(
        items: dict[str, WatchHistoryItem], tmdb_service: "TMDBService"
    ) -> list[WatchHistoryItem]:
        """Scrob keys media on TMDB ids; IMDb ids are present but optional."""
        resolved: list[WatchHistoryItem] = []
        pending: list[WatchHistoryItem] = []
        for key, item in items.items():
            if key.startswith("tt"):
                resolved.append(item)
            elif key.startswith("tmdb:"):
                pending.append(item)

        sem = asyncio.Semaphore(DEFAULT_CONCURRENCY_LIMIT)

        async def lookup(item: WatchHistoryItem) -> str | None:
            async with sem:
                return await tmdb_service.get_imdb_id(item.type, int(item.imdb_id[5:]))

        for item, imdb_id in zip(pending, await asyncio.gather(*(lookup(item) for item in pending))):
            if imdb_id:
                item.imdb_id = imdb_id
                resolved.append(item)
        return resolved

    @staticmethod
    def _parse_date(date_str: str | None) -> datetime | None:
        if not date_str:
            return None
        try:
            return datetime.fromisoformat(str(date_str).replace("Z", "+00:00"))
        except ValueError:
            return None

    @staticmethod
    def account_identity(base_url: str, api_key: str) -> str:
        """Stable identity for one Scrob account.

        Scrob's API-key surface exposes no user id, so the identity is a hash
        of the instance URL and the key: stable per account, and it keeps the
        raw key out of the stored identities.
        """
        digest = hashlib.sha256(f"{base_url.rstrip('/')}:{api_key}".encode()).hexdigest()
        return digest[:16]


scrob_service = ScrobService()
