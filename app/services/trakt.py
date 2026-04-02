import asyncio
from typing import Any

from httpx import AsyncClient
from loguru import logger

from app.core.config import settings
from app.models.history import WatchHistory, WatchHistoryItem


class TraktService:
    """Service for interacting with the Trakt API."""

    BASE_URL = "https://api.trakt.tv"

    def __init__(self):
        self.client = AsyncClient(timeout=15)

    def _headers(self, access_token: str) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "trakt-api-version": "2",
            "trakt-api-key": settings.TRAKT_CLIENT_ID or "",
            "Authorization": f"Bearer {access_token}",
        }

    async def get_user_info(self, access_token: str) -> dict[str, Any]:
        """GET /users/me - validate token and get username."""
        response = await self.client.get(
            f"{self.BASE_URL}/users/me",
            headers=self._headers(access_token),
            follow_redirects=True,
        )
        response.raise_for_status()
        return response.json()

    async def exchange_code(self, code: str, redirect_uri: str) -> dict[str, Any]:
        """Exchange authorization code for tokens."""
        response = await self.client.post(
            f"{self.BASE_URL}/oauth/token",
            json={
                "code": code,
                "client_id": settings.TRAKT_CLIENT_ID,
                "client_secret": settings.TRAKT_CLIENT_SECRET,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            follow_redirects=True,
        )
        response.raise_for_status()
        return response.json()

    async def refresh_token(self, refresh_token: str, redirect_uri: str) -> dict[str, Any]:
        """Refresh expired Trakt access token."""
        response = await self.client.post(
            f"{self.BASE_URL}/oauth/token",
            json={
                "refresh_token": refresh_token,
                "client_id": settings.TRAKT_CLIENT_ID,
                "client_secret": settings.TRAKT_CLIENT_SECRET,
                "redirect_uri": redirect_uri,
                "grant_type": "refresh_token",
            },
            follow_redirects=True,
        )
        response.raise_for_status()
        return response.json()

    async def get_history(self, access_token: str) -> WatchHistory:
        """Fetch watched + rated items, return as WatchHistory."""
        headers = self._headers(access_token)

        # Fetch all 4 endpoints in parallel
        watched_movies_coro = self.client.get(
            f"{self.BASE_URL}/users/me/watched/movies",
            headers=headers,
            follow_redirects=True,
        )
        watched_shows_coro = self.client.get(
            f"{self.BASE_URL}/users/me/watched/shows",
            headers=headers,
            follow_redirects=True,
        )
        rated_movies_coro = self.client.get(
            f"{self.BASE_URL}/users/me/ratings/movies",
            headers=headers,
            follow_redirects=True,
        )
        rated_shows_coro = self.client.get(
            f"{self.BASE_URL}/users/me/ratings/shows",
            headers=headers,
            follow_redirects=True,
        )

        results = await asyncio.gather(
            watched_movies_coro,
            watched_shows_coro,
            rated_movies_coro,
            rated_shows_coro,
            return_exceptions=True,
        )

        watched_movies = self._safe_json(results[0])
        watched_shows = self._safe_json(results[1])
        rated_movies = self._safe_json(results[2])
        rated_shows = self._safe_json(results[3])

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
    def _safe_json(result) -> list:
        if isinstance(result, Exception):
            logger.warning(f"Trakt API request failed: {result}")
            return []
        try:
            result.raise_for_status()
            return result.json()
        except Exception as e:
            logger.warning(f"Failed to parse Trakt response: {e}")
            return []

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
