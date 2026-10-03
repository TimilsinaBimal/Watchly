import asyncio
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from loguru import logger

from app.core.base_client import BaseClient
from app.core.constants import DEFAULT_CONCURRENCY_LIMIT
from app.models.history import WatchHistory, WatchHistoryItem

if TYPE_CHECKING:
    from app.services.tmdb.service import TMDBService

# Nuvio's public API (https://nuvio.tv/docs/nuvio-public-api.md): a Supabase
# surface behind one published key. The key is a client identifier, not a secret.
BASE_URL = "https://api.nuvio.tv"
PUBLISHABLE_KEY = "sb_publishable_1Clq8rlTVACkdcZuqr6_AD__xUUC_EN"

# A progress row counts as watched once this much of the runtime was played.
FINISHED_COMPLETION = 0.9
# ponytail: the snapshot RPC returns at most 200 progress rows; the full watched
# list comes from sync_pull_watched_items, so this only adds recent unfinished
# plays. Switch to sync_pull_watch_progress_delta if 200 proves too few.
PROGRESS_ROW_LIMIT = 200
# Nuvio's documented default page size: the whole list in one call.
WATCHED_PAGE_SIZE = 100000


class NuvioService:
    def __init__(self):
        self.client = BaseClient(base_url=BASE_URL, timeout=20.0, max_retries=3)

    async def close(self) -> None:
        await self.client.close()

    @staticmethod
    def _headers(access_token: str | None = None) -> dict[str, str]:
        headers = {"apikey": PUBLISHABLE_KEY, "Content-Type": "application/json"}
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        return headers

    async def get_user_id(self, access_token: str) -> str | None:
        """Nuvio user id for a session, or None when Nuvio won't confirm it."""
        try:
            user = await self.client.get("/auth/v1/user", headers=self._headers(access_token))
        except Exception as e:
            logger.info(f"Nuvio identity lookup failed: {type(e).__name__}")
            return None
        user_id = user.get("id")
        return str(user_id) if user_id else None

    async def refresh(self, refresh_token: str) -> dict[str, Any]:
        """New session for a refresh token. Raises when Nuvio rejects it."""
        return await self.client.post(
            "/auth/v1/token",
            params={"grant_type": "refresh_token"},
            json={"refresh_token": refresh_token},
            headers=self._headers(),
        )

    async def _rpc(self, function: str, params: dict[str, Any], access_token: str) -> list[dict[str, Any]]:
        rows = await self.client.post(f"/rest/v1/rpc/{function}", json=params, headers=self._headers(access_token))
        # BaseClient is annotated dict, but PostgREST RPCs return a JSON array.
        return rows if isinstance(rows, list) else []

    async def get_history(self, access_token: str, profile_id: int, tmdb_service: "TMDBService") -> WatchHistory:
        """Watched titles of one Nuvio profile, keyed on IMDb ids.

        Nuvio has no ratings, so every title lands in "watched"; a series counts
        once however many episodes were played. A failed call raises rather than
        degrading to an empty list, which the callers would cache as the library.
        """
        watched, progress = await asyncio.gather(
            self._rpc(
                "sync_pull_watched_items",
                {"p_profile_id": profile_id, "p_page": 1, "p_page_size": WATCHED_PAGE_SIZE},
                access_token,
            ),
            self._rpc(
                "sync_pull_watch_progress",
                {"p_profile_id": profile_id, "p_limit": PROGRESS_ROW_LIMIT},
                access_token,
            ),
        )

        items: dict[str, WatchHistoryItem] = {}
        for row in watched:
            self._merge(items, row, 1.0, row.get("watched_at"))
        for row in progress:
            duration = int(row.get("duration") or 0)
            completion = min(int(row.get("position") or 0) / duration, 1.0) if duration > 0 else 0.0
            if completion >= FINISHED_COMPLETION:
                self._merge(items, row, completion, row.get("last_watched"))

        resolved = await self._resolve_imdb_ids(items, tmdb_service)
        logger.info(f"Nuvio history: {len(resolved)} of {len(items)} titles resolved to IMDb ids")
        return WatchHistory(items=resolved, source="nuvio")

    @staticmethod
    def _merge(items: dict[str, WatchHistoryItem], row: dict[str, Any], completion: float, watched_at: Any) -> None:
        content_id = str(row.get("content_id") or "")
        mtype = {"movie": "movie", "series": "series"}.get(str(row.get("content_type") or ""))
        if not content_id or mtype is None:
            return
        millis = int(watched_at or 0)
        last_watched = datetime.fromtimestamp(millis / 1000, tz=timezone.utc) if millis > 0 else None

        existing = items.get(content_id)
        if existing is None:
            items[content_id] = WatchHistoryItem(
                imdb_id=content_id,
                type=mtype,
                name=str(row.get("title") or row.get("name") or ""),
                completion=completion,
                last_watched=last_watched,
                source="nuvio",
            )
            return
        existing.completion = max(existing.completion, completion)
        if last_watched and (existing.last_watched is None or last_watched > existing.last_watched):
            existing.last_watched = last_watched

    @staticmethod
    async def _resolve_imdb_ids(
        items: dict[str, WatchHistoryItem], tmdb_service: "TMDBService"
    ) -> list[WatchHistoryItem]:
        """Nuvio stores whatever id the producing addon used: `tt…` or `tmdb:…`."""
        resolved: list[WatchHistoryItem] = []
        pending: list[WatchHistoryItem] = []
        for content_id, item in items.items():
            if content_id.startswith("tt"):
                resolved.append(item)
            elif content_id.startswith("tmdb:") and content_id[5:].isdigit():
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


nuvio_service = NuvioService()
