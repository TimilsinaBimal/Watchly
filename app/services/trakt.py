import asyncio
from typing import Any

from loguru import logger

from app.core.base_client import BaseClient
from app.core.config import settings
from app.models.history import WatchHistory, WatchHistoryItem


class TraktService:
    """Service for interacting with the Trakt API."""

    BASE_URL = "https://api.trakt.tv"

    def __init__(self):
        self.client = BaseClient(base_url=self.BASE_URL, timeout=15.0, max_retries=3)

    async def close(self) -> None:
        await self.client.close()

    def _headers(self, access_token: str) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "trakt-api-version": "2",
            "trakt-api-key": settings.TRAKT_CLIENT_ID or "",
            "Authorization": f"Bearer {access_token}",
        }

    async def get_user_info(self, access_token: str) -> dict[str, Any]:
        """GET /users/me - validate token and get username."""
        return await self.client.get("/users/me", headers=self._headers(access_token))

    async def exchange_code(self, code: str, redirect_uri: str) -> dict[str, Any]:
        """Exchange authorization code for tokens."""
        return await self.client.post(
            "/oauth/token",
            json={
                "code": code,
                "client_id": settings.TRAKT_CLIENT_ID,
                "client_secret": settings.TRAKT_CLIENT_SECRET,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )

    async def refresh_token(self, refresh_token: str, redirect_uri: str) -> dict[str, Any]:
        """Refresh expired Trakt access token."""
        return await self.client.post(
            "/oauth/token",
            json={
                "refresh_token": refresh_token,
                "client_id": settings.TRAKT_CLIENT_ID,
                "client_secret": settings.TRAKT_CLIENT_SECRET,
                "redirect_uri": redirect_uri,
                "grant_type": "refresh_token",
            },
        )

    async def get_history(self, access_token: str) -> WatchHistory:
        """Fetch watched + rated items, return as WatchHistory."""
        headers = self._headers(access_token)

        # Fetch all 4 endpoints in parallel; BaseClient returns parsed JSON
        # and handles retry on 429/5xx internally.
        results = await asyncio.gather(
            self.client.get("/users/me/watched/movies", headers=headers),
            self.client.get("/users/me/watched/shows", headers=headers),
            self.client.get("/users/me/ratings/movies", headers=headers),
            self.client.get("/users/me/ratings/shows", headers=headers),
            return_exceptions=True,
        )

        watched_movies = self._safe_list(results[0], "watched/movies")
        watched_shows = self._safe_list(results[1], "watched/shows")
        rated_movies = self._safe_list(results[2], "ratings/movies")
        rated_shows = self._safe_list(results[3], "ratings/shows")

        # Build rating lookup: imdb_id -> rating (1-10)
        ratings: dict[str, float] = {}
        for item in rated_movies + rated_shows:
            media = item.get("movie") or item.get("show") or {}
            imdb_id = media.get("ids", {}).get("imdb")
            if imdb_id and item.get("rating"):
                ratings[imdb_id] = float(item["rating"])

        # Convert watched items to WatchHistoryItem
        items: list[WatchHistoryItem] = []
        seen_ids: set[str] = set()

        for entry in watched_movies:
            movie = entry.get("movie", {})
            imdb_id = movie.get("ids", {}).get("imdb")
            if not imdb_id or imdb_id in seen_ids:
                continue
            seen_ids.add(imdb_id)
            items.append(
                WatchHistoryItem(
                    imdb_id=imdb_id,
                    type="movie",
                    name=movie.get("title", ""),
                    rating=ratings.get(imdb_id),
                    watch_count=entry.get("plays", 1),
                    completion=1.0,
                    last_watched=self._parse_date(entry.get("last_watched_at")),
                    source="trakt",
                )
            )

        for entry in watched_shows:
            show = entry.get("show", {})
            imdb_id = show.get("ids", {}).get("imdb")
            if not imdb_id or imdb_id in seen_ids:
                continue
            seen_ids.add(imdb_id)
            items.append(
                WatchHistoryItem(
                    imdb_id=imdb_id,
                    type="series",
                    name=show.get("title", ""),
                    rating=ratings.get(imdb_id),
                    watch_count=entry.get("plays", 1),
                    completion=1.0,
                    last_watched=self._parse_date(entry.get("last_watched_at")),
                    source="trakt",
                )
            )

        # Add rated-but-not-watched items (user rated without watching on Trakt)
        for item in rated_movies + rated_shows:
            media = item.get("movie") or item.get("show") or {}
            imdb_id = media.get("ids", {}).get("imdb")
            if not imdb_id or imdb_id in seen_ids:
                continue
            seen_ids.add(imdb_id)
            mtype = "movie" if "movie" in item else "series"
            items.append(
                WatchHistoryItem(
                    imdb_id=imdb_id,
                    type=mtype,
                    name=media.get("title", ""),
                    rating=float(item.get("rating", 0)),
                    watch_count=0,
                    completion=0.0,
                    last_watched=self._parse_date(item.get("rated_at")),
                    source="trakt",
                )
            )

        logger.info(f"Trakt history: {len(items)} items ({len(ratings)} rated)")
        return WatchHistory(items=items, source="trakt")

    @staticmethod
    def _safe_list(result, label: str) -> list:
        if isinstance(result, Exception):
            logger.warning(f"Trakt {label} request failed: {result}")
            return []
        # BaseClient returns dict for JSON objects; Trakt list endpoints return
        # arrays which BaseClient parses to list — but its type is annotated as
        # dict. Accept either shape defensively.
        if isinstance(result, list):
            return result
        if isinstance(result, dict) and not result:
            return []
        return result if isinstance(result, list) else []

    @staticmethod
    def _parse_date(date_str: str | None):
        if not date_str:
            return None
        try:
            from datetime import datetime

            return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None


trakt_service = TraktService()
