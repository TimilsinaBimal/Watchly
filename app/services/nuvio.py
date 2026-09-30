"""Nuvio account watch history, read through Nuvio's own sync backend.

Nuvio (nuvio.tv) keeps an account's watch history in a Supabase project it
advertises at `GET {backend}/.well-known/nuvio`. Two PostgREST RPCs serve it:
`sync_pull_watch_progress` (position/duration per video) and
`sync_pull_watched_items` (the app's watched list). Both are SECURITY DEFINER
and resolve the owning account from the caller's session, so a plain
email/password login is enough to read them.

This API is unofficial and unversioned: it is what Nuvio's own clients use.
Anything that fails here must degrade to the caller's Stremio fallback rather
than raise through a catalog request.
"""

import asyncio
import time
from datetime import datetime, timezone
from typing import Any

from async_lru import alru_cache
from loguru import logger

from app.core.base_client import BaseClient
from app.models.history import WatchHistory, WatchHistoryItem

DISCOVERY_URL = "https://api.nuvio.tv/.well-known/nuvio"
# Nuvio's own page size for the watched-items pull loop.
WATCHED_ITEMS_PAGE_SIZE = 500
# Backstop against a pagination contract change turning the loop endless. 100
# pages at 500 rows is 50k entries — far past any real history.
MAX_WATCHED_ITEMS_PAGES = 100
# Progress rows only appear in the history when the app got far enough to matter.
MIN_PROGRESS_COMPLETION = 0.5
# Refresh this far ahead of expiry. Nuvio hands out week-long access tokens,
# so this is a safety net rather than the hot path.
REFRESH_WINDOW_SECONDS = 600


@alru_cache(maxsize=1, ttl=21600)
async def discover() -> tuple[str, str]:
    """(backend_url, publishable_key) from Nuvio's discovery document.

    Cached for six hours: the document is static, and a cold lookup on every
    history fetch would add a round trip to a request already doing several.
    """
    client = BaseClient(timeout=10.0, max_retries=2)
    try:
        document = await client.get(DISCOVERY_URL)
    finally:
        await client.close()

    backend_url = str(document.get("backend_url") or "").rstrip("/")
    publishable_key = str(document.get("publishable_key") or "")
    if not backend_url or not publishable_key:
        raise ValueError("Nuvio discovery document is missing backend_url or publishable_key")
    return backend_url, publishable_key


class NuvioService:
    """Auth + watch history for one Nuvio account."""

    def __init__(self) -> None:
        self._client: BaseClient | None = None
        self._key = ""

    async def _client_and_key(self) -> tuple[BaseClient, str]:
        """The backend client, built once from the discovery document.

        Discovery advertises a stable backend URL, so the client outlives a
        single fetch — same long-lived pattern as the Trakt and Simkl services.
        """
        if self._client is None:
            backend_url, self._key = await discover()
            self._client = BaseClient(base_url=backend_url, timeout=20.0, max_retries=2)
        return self._client, self._key

    async def close(self) -> None:
        """Close the backend client."""
        if self._client is not None:
            await self._client.close()
            self._client = None

    async def login(self, email: str, password: str) -> dict[str, Any]:
        """Exchange credentials for a session. Raises on bad credentials."""
        client, key = await self._client_and_key()
        data = await client.post(
            "/auth/v1/token",
            params={"grant_type": "password"},
            json={"email": email, "password": password},
            headers={"apikey": key, "Content-Type": "application/json"},
        )
        if not data.get("access_token"):
            raise ValueError("Nuvio did not return a session for those credentials")
        return data

    async def refresh(self, refresh_token: str) -> dict[str, Any] | None:
        """Fresh session from a refresh token, or None if Nuvio won't renew it."""
        try:
            client, key = await self._client_and_key()
            data = await client.post(
                "/auth/v1/token",
                params={"grant_type": "refresh_token"},
                json={"refresh_token": refresh_token},
                headers={"apikey": key, "Content-Type": "application/json"},
            )
        except Exception as e:
            logger.warning(f"Nuvio token refresh failed: {type(e).__name__}")
            return None

        return data if data.get("access_token") else None

    async def get_user_id(self, access_token: str) -> str | None:
        """Nuvio user id for a session, or None when Nuvio won't confirm it."""
        try:
            client, key = await self._client_and_key()
            user = await client.get(
                "/auth/v1/user",
                headers={"apikey": key, "Authorization": f"Bearer {access_token}"},
            )
        except Exception as e:
            logger.info(f"Nuvio identity lookup failed: {type(e).__name__}")
            return None

        user_id = user.get("id")
        return str(user_id) if user_id else None

    async def get_profiles(self, access_token: str) -> list[dict[str, Any]]:
        """Nuvio profiles on the account (profile_index is the id used below)."""
        rows = await self._rpc("sync_pull_profiles", {}, access_token)
        return rows if isinstance(rows, list) else []

    async def get_watch_history(
        self, access_token: str, profile_id: int, tmdb_api_key: str | None = None
    ) -> WatchHistory:
        """Watched titles for one Nuvio profile, as a source-agnostic history."""
        progress = await self._rpc("sync_pull_watch_progress", {"p_profile_id": profile_id}, access_token)
        watched = await self._pull_watched_items(access_token, profile_id)

        items: dict[str, WatchHistoryItem] = {}
        for row in progress:
            self._merge_progress(items, row)
        for row in watched:
            self._merge_watched(items, row)

        resolved, unresolved = await self._resolve_imdb_ids(items, tmdb_api_key)
        if unresolved:
            logger.info(
                f"Nuvio history: {len(resolved)} of {len(items)} items resolved to IMDb ids; "
                f"{unresolved} skipped (unsupported content id prefixes)"
            )
        return WatchHistory(items=list(resolved.values()), source="nuvio")

    async def _pull_watched_items(self, access_token: str, profile_id: int) -> list[dict[str, Any]]:
        """Every page of the watched-items snapshot."""
        rows: list[dict[str, Any]] = []
        for page in range(1, MAX_WATCHED_ITEMS_PAGES + 1):
            page_rows = await self._rpc(
                "sync_pull_watched_items",
                {"p_profile_id": profile_id, "p_page": page, "p_page_size": WATCHED_ITEMS_PAGE_SIZE},
                access_token,
            )
            if not isinstance(page_rows, list):
                return rows
            rows.extend(page_rows)
            if len(page_rows) < WATCHED_ITEMS_PAGE_SIZE:
                return rows

        logger.warning(f"Nuvio watched items: stopped at the {MAX_WATCHED_ITEMS_PAGES}-page cap with {len(rows)} rows")
        return rows

    async def _rpc(self, function: str, params: dict[str, Any], access_token: str) -> Any:
        client, key = await self._client_and_key()
        return await client.post(
            f"/rest/v1/rpc/{function}",
            json=params,
            headers={
                "apikey": key,
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
        )

    @staticmethod
    def _merge_progress(items: dict[str, WatchHistoryItem], row: dict[str, Any]) -> None:
        """Fold one progress row into the per-title history."""
        content_id = str(row.get("content_id") or "")
        content_type = _content_type(row.get("content_type"))
        if not content_id or content_type is None:
            return

        duration = _int(row.get("duration"))
        position = _int(row.get("position"))
        completion = min(max(position / duration, 0.0), 1.0) if duration > 0 else 0.0
        last_watched = _timestamp(row.get("last_watched"))

        existing = items.get(content_id)
        if existing is not None:
            # An item already in the history still moves forward on a barely-started
            # row — the seed for "Because you watched …" is picked by recency.
            existing.completion = max(existing.completion, completion)
            existing.last_watched = _latest(existing.last_watched, last_watched)
            return

        if completion < MIN_PROGRESS_COMPLETION:
            # Started and abandoned: not history yet, so it must not seed a row.
            return

        items[content_id] = WatchHistoryItem(
            imdb_id=content_id,
            type=content_type,
            name=str(row.get("title") or ""),
            completion=completion,
            last_watched=last_watched,
            source="nuvio",
        )

    @staticmethod
    def _merge_watched(items: dict[str, WatchHistoryItem], row: dict[str, Any]) -> None:
        """Fold one watched-items row into the per-title history.

        The watched list is the app's own record of what was finished, so it
        wins the name and the timestamp even when a progress row got there first.
        """
        content_id = str(row.get("content_id") or "")
        content_type = _content_type(row.get("content_type"))
        if not content_id or content_type is None:
            return

        existing = items.get(content_id)
        title = str(row.get("title") or "")
        last_watched = _timestamp(row.get("watched_at"))

        if existing is None:
            items[content_id] = WatchHistoryItem(
                imdb_id=content_id,
                type=content_type,
                name=title,
                completion=1.0,
                last_watched=last_watched,
                source="nuvio",
            )
            return

        existing.name = existing.name or title
        existing.last_watched = _latest(existing.last_watched, last_watched)

    @staticmethod
    async def _resolve_imdb_ids(
        items: dict[str, WatchHistoryItem], tmdb_api_key: str | None
    ) -> tuple[dict[str, WatchHistoryItem], int]:
        """Keep only items with an IMDb id, resolving `tmdb:` ids through TMDB.

        Watchly keys everything on `tt…` ids, and Nuvio stores whatever the
        addon that produced the item used — `tmdb:123` for TMDB-keyed catalogs.
        Items with ids no reliable mapping exists for are dropped here rather
        than fanned into empty TMDB lookups downstream.
        """
        resolved: dict[str, WatchHistoryItem] = {}
        pending: list[tuple[str, WatchHistoryItem]] = []
        unresolved = 0

        for content_id, item in items.items():
            if content_id.startswith("tt"):
                resolved[content_id] = item
            elif content_id.startswith("tmdb:") and tmdb_api_key:
                pending.append((content_id, item))
            else:
                unresolved += 1

        if pending:
            from app.services.tmdb.service import get_tmdb_service

            # The process-wide service, not a fresh client: history refreshes are
            # frequent and a per-call TMDB client leaks a connection pool each time.
            service = get_tmdb_service(api_key=tmdb_api_key)
            imdb_ids = await asyncio.gather(
                *(service.get_imdb_id(item.type, int(content_id.split(":", 1)[1])) for content_id, item in pending),
                return_exceptions=True,
            )

            for (content_id, item), imdb_id in zip(pending, imdb_ids, strict=True):
                if isinstance(imdb_id, str) and imdb_id.startswith("tt"):
                    item.imdb_id = imdb_id
                    resolved[imdb_id] = item
                else:
                    unresolved += 1

        return resolved, unresolved


def _content_type(value: Any) -> str | None:
    """Nuvio content types folded onto the two Watchly knows."""
    return {"movie": "movie", "series": "series", "tv": "series"}.get(str(value or "").lower())


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _timestamp(value: Any) -> datetime | None:
    """Epoch milliseconds to UTC datetime, as Nuvio stores it."""
    millis = _int(value)
    return datetime.fromtimestamp(millis / 1000, tz=timezone.utc) if millis > 0 else None


def _latest(current: datetime | None, candidate: datetime | None) -> datetime | None:
    if current is None:
        return candidate
    if candidate is None:
        return current
    return max(current, candidate)


def is_expiring(expires_at: int | None) -> bool:
    """True when an access token is within the refresh window (or undated)."""
    if not expires_at:
        return True
    return time.time() >= expires_at - REFRESH_WINDOW_SECONDS


nuvio_service = NuvioService()
