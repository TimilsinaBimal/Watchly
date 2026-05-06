from typing import Any

from loguru import logger

from app.services.trakt.client import TraktClient


class TraktLibraryService:
    """
    Fetches and normalises watch history from Trakt into the same shape
    that the Stremio library service produces, so the rest of the app
    needs no changes.
    """

    # How many pages of history to pull (1 000 items / page)
    MAX_PAGES = 10

    def __init__(self, client: TraktClient):
        self.client = client

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    async def get_library_items(self) -> dict[str, list[dict[str, Any]]]:
        """
        Return library items in the same shape as StremioLibraryService:
        { "watched": [...], "loved": [], "liked": [], "added": [], "removed": [] }

        Each item contains at minimum:
          _id       – tt... or tmdb:... string
          type      – "movie" | "series"
          name      – title
        """
        try:
            movies = await self._get_history("movies")
            shows = await self._get_history("shows")

            watched: list[dict[str, Any]] = []
            seen_ids: set[str] = set()

            for raw in movies:
                item = self._normalise_movie(raw)
                if item and item["_id"] not in seen_ids:
                    seen_ids.add(item["_id"])
                    watched.append(item)

            for raw in shows:
                item = self._normalise_show(raw)
                if item and item["_id"] not in seen_ids:
                    seen_ids.add(item["_id"])
                    watched.append(item)

            logger.info(f"[Trakt] library: {len(watched)} watched items ({len(movies)} movies, {len(shows)} shows)")

            return {
                "watched": watched,
                "loved": [],
                "liked": [],
                "added": [],
                "removed": [],
            }
        except Exception as e:
            logger.exception(f"[Trakt] Failed to get library items: {e}")
            return {"watched": [], "loved": [], "liked": [], "added": [], "removed": []}

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _get_history(self, media_type: str) -> list[dict[str, Any]]:
        """
        Pull watched history for *media_type* ("movies" | "shows").
        Uses the /users/me/watched/:type endpoint which returns a deduplicated
        list of everything the user has ever played (no paging needed).
        """
        try:
            data = await self.client.get(f"/users/me/watched/{media_type}")
            if isinstance(data, list):
                return data
            return []
        except Exception as e:
            logger.warning(f"[Trakt] Failed to fetch {media_type} history: {e}")
            return []

    def _get_id(self, ids: dict[str, Any]) -> str | None:
        """Return the best available canonical ID (prefer IMDb, fall back to TMDB)."""
        imdb = ids.get("imdb")
        if imdb:
            return imdb  # e.g. "tt1234567"
        tmdb = ids.get("tmdb")
        if tmdb:
            return f"tmdb:{tmdb}"
        return None

    def _normalise_movie(self, raw: dict[str, Any]) -> dict[str, Any] | None:
        movie = raw.get("movie", {})
        ids = movie.get("ids", {})
        canonical_id = self._get_id(ids)
        if not canonical_id:
            return None
        return {
            "_id": canonical_id,
            "type": "movie",
            "name": movie.get("title", ""),
            "year": movie.get("year"),
            "state": {
                "timesWatched": raw.get("plays", 1),
                "flaggedWatched": 1,
                "lastWatched": raw.get("last_watched_at", ""),
            },
            "temp": False,
            "removed": False,
            "_source": "trakt",
        }

    def _normalise_show(self, raw: dict[str, Any]) -> dict[str, Any] | None:
        show = raw.get("show", {})
        ids = show.get("ids", {})
        canonical_id = self._get_id(ids)
        if not canonical_id:
            return None
        return {
            "_id": canonical_id,
            "type": "series",
            "name": show.get("title", ""),
            "year": show.get("year"),
            "state": {
                "timesWatched": raw.get("plays", 1),
                "flaggedWatched": 1,
                "lastWatched": raw.get("last_watched_at", ""),
            },
            "temp": False,
            "removed": False,
            "_source": "trakt",
        }
