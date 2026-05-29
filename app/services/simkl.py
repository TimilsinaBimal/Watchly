import asyncio
from datetime import datetime
from typing import Any

import httpx
from cachetools import TTLCache
from loguru import logger

from app.core.base_client import BaseClient
from app.models.history import WatchHistory, WatchHistoryItem


def get_popularity(rank: int | None, N: int = 100000, K: int = 100) -> float:
    if rank is None:
        rank = 50000
    return (N - rank + 1) / N * K


def normalize_simkl_to_tmdb(item: dict[str, Any], mtype: str) -> dict[str, Any]:
    """
    Convert Simkl item format to TMDB-compatible format.

    Mappings:
    - item["ratings"]["simkl"]["rating"] → vote_average
    - item["ratings"]["simkl"]["votes"] → vote_count (default 1000 if missing)
    - item["year"] or item["released"] → release_date/first_air_date
    - item["ids"]["tmdb"] → id
    """
    ids = item.get("ids", {})
    ratings = item.get("ratings", {})
    simkl_ratings = ratings.get("simkl", {})

    # Extract release date
    released = item.get("released")
    year = item.get("year")
    if released:
        release_date = released
    elif year:
        release_date = f"{year}-01-01"
    else:
        release_date = None

    normalized = {
        "id": ids.get("tmdb"),
        "vote_average": simkl_ratings.get("rating", 0),
        "vote_count": simkl_ratings.get("votes", 1000),  # Default to 1000 if not available
        "genre_ids": [],  # Simkl uses different genre format, leave empty for TMDB enrichment
        "popularity": get_popularity(item.get("rank", 50000)),  # Estimate from rank if available
        "_simkl_id": ids.get("simkl"),
        "_imdb_id": ids.get("imdb"),
    }

    # Set appropriate date field based on media type
    if mtype == "tv":
        normalized["first_air_date"] = release_date
    else:
        normalized["release_date"] = release_date

    return normalized


class SimklService:
    def __init__(self):
        self.base_url = "https://api.simkl.com"
        self.client = BaseClient(base_url=self.base_url, timeout=10.0, max_retries=3)
        self._semaphore = asyncio.Semaphore(10)  # Max 10 concurrent requests
        self._details_cache: TTLCache = TTLCache(maxsize=1000, ttl=3600)  # 1 hour TTL

    async def close(self) -> None:
        await self.client.close()

    async def exchange_code(self, code: str, redirect_uri: str, client_id: str, client_secret: str) -> dict[str, Any]:
        """Exchange authorization code for an access token."""
        return await self.client.post(
            "/oauth/token",
            json={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )

    async def get_user_settings(self, access_token: str, client_id: str) -> dict[str, Any]:
        """Fetch the authenticated user's profile (used to display 'Connected as ...')."""
        headers = {
            "Authorization": f"Bearer {access_token}",
            "simkl-api-key": client_id,
        }
        return await self.client.get("/users/settings", headers=headers)

    async def _fetch_with_semaphore(self, coro):
        """Execute a coroutine with semaphore for rate limiting."""
        async with self._semaphore:
            return await coro

    async def get_trending(self, api_key: str):
        try:
            return await self.client.get("/movies/trending", params={"client_id": api_key})
        except httpx.HTTPStatusError as e:
            # 401/403 indicate the user's Simkl token was revoked — let those
            # propagate so callers can clear the token and prompt re-auth.
            if e.response.status_code in (401, 403):
                raise
            logger.warning(f"Simkl trending returned {e.response.status_code}: {e}")
            return []
        except httpx.RequestError as e:
            logger.warning(f"Simkl trending request failed: {e}")
            return []

    async def get_item_details(self, simkl_id, mtype: str, api_key: str) -> dict[str, Any]:
        """Fetch full item details from Simkl with caching."""
        cache_key = f"{simkl_id}:{mtype}"

        if cache_key in self._details_cache:
            logger.debug(f"Cache hit for Simkl item {simkl_id}")
            return self._details_cache[cache_key]

        mtype_path = "movies" if mtype == "movie" else "tv"
        try:
            result = await self.client.get(
                f"/{mtype_path}/{simkl_id}",
                params={"client_id": api_key, "extended": "full"},
            )
            self._details_cache[cache_key] = result
            return result
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (401, 403):
                raise
            logger.warning(f"Simkl item details {simkl_id} returned {e.response.status_code}: {e}")
            return {}
        except httpx.RequestError as e:
            logger.warning(f"Simkl item details {simkl_id} request failed: {e}")
            return {}

    async def get_history(self, access_token: str, client_id: str) -> WatchHistory:
        """Fetch watch history from Simkl using OAuth access token."""
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}",
            "simkl-api-key": client_id,
        }

        results = await asyncio.gather(
            self.client.get("/sync/all-items/movies", headers=headers),
            self.client.get("/sync/all-items/shows", headers=headers),
            return_exceptions=True,
        )

        items: list[WatchHistoryItem] = []
        seen: set[str] = set()

        for idx, result in enumerate(results):
            if isinstance(result, Exception):
                logger.warning(f"Simkl sync request failed: {result}")
                continue
            data = result if isinstance(result, dict) else {}
            mtype = "movie" if idx == 0 else "series"
            entries = data.get("movies", []) if idx == 0 else data.get("shows", [])

            for entry in entries:
                media = entry.get("movie") or entry.get("show") or {}
                imdb_id = media.get("ids", {}).get("imdb")
                if not imdb_id or imdb_id in seen:
                    continue
                seen.add(imdb_id)

                user_rating = entry.get("user_rating")
                rating = float(user_rating) if user_rating is not None else None

                last_watched = None
                raw_date = entry.get("last_watched_at")
                if raw_date:
                    try:
                        last_watched = datetime.fromisoformat(str(raw_date).replace("Z", "+00:00"))
                    except (ValueError, TypeError):
                        pass

                # watch_count is a rewatch signal downstream (is_rewatched, the
                # >=2 "loved" proxy). Only movies expose a real replay count;
                # for shows every Simkl count is episode-based, so a fully
                # watched multi-episode series would look rewatched and get
                # mis-loved. Leave series at 1 and let ratings drive loved/liked.
                if mtype == "movie":
                    try:
                        watch_count = max(int(entry.get("total_plays_count") or 0), 1)
                    except (TypeError, ValueError):
                        watch_count = 1
                else:
                    watch_count = 1

                items.append(
                    WatchHistoryItem(
                        imdb_id=imdb_id,
                        type=mtype,
                        name=media.get("title", ""),
                        rating=rating,
                        watch_count=watch_count,
                        completion=1.0,
                        last_watched=last_watched,
                        source="simkl",
                    )
                )

        logger.info(f"Simkl history: {len(items)} items")
        return WatchHistory(items=items, source="simkl")

    async def get_recommendations(self, imdb_id: str, mtype: str, api_key: str) -> list[dict[str, Any]]:
        """Get recommendations for a single item (original method for item-based)."""
        item_details = await self.get_item_details(imdb_id, mtype, api_key)
        if not item_details:
            return []

        recommendations = item_details.get("users_recommendations", [])
        logger.info(f"Extending simkl recommendations for {imdb_id}")

        tasks = [self.get_item_details(rec.get("ids", {}).get("simkl"), mtype, api_key) for rec in recommendations]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        final_results = []
        for result in results:
            if isinstance(result, Exception):
                logger.error(f"Error fetching details from Simkl: {result}")
                continue
            if not result:
                continue

            # Add TMDB ID for compatibility
            result["id"] = result.get("ids", {}).get("tmdb")
            final_results.append(result)

        return final_results

    async def get_recommendations_batch(
        self,
        imdb_ids: list[str],
        mtype: str,
        api_key: str,
        max_per_item: int = 8,
        year_min: int | None = None,
        year_max: int | None = None,
    ) -> list[dict[str, Any]]:
        """
        Fetch recommendations for multiple items efficiently.

        Optimizations:
        1. Parallel fetch with semaphore (max 10 concurrent)
        2. Limit recommendations per source item
        3. Skip detail fetch if TMDB ID already present
        4. Deduplicate across all source items
        5. Early year filtering to reduce API calls
        6. In-memory cache for item details

        Args:
            imdb_ids: List of IMDB IDs to get recommendations for
            mtype: Media type (movie/tv)
            api_key: Simkl API key
            max_per_item: Max recommendations per source item
            year_min: Minimum year for filtering (optional)
            year_max: Maximum year for filtering (optional)

        Returns:
            List of normalized TMDB-compatible items
        """
        logger.info(f"Fetching Simkl recommendations batch for {len(imdb_ids)} items")

        # Step 1: Fetch item details for all source items (to get users_recommendations)
        detail_tasks = [
            self._fetch_with_semaphore(self.get_item_details(imdb_id, mtype, api_key)) for imdb_id in imdb_ids
        ]
        source_details = await asyncio.gather(*detail_tasks, return_exceptions=True)

        # Step 2: Collect all recommendations, deduplicate by simkl_id
        all_recs: dict[int, dict] = {}  # simkl_id -> rec data
        needs_detail_fetch: list[int] = []  # simkl_ids that need full details

        for detail in source_details:
            if isinstance(detail, Exception) or not detail:
                continue

            recs = detail.get("users_recommendations", [])[:max_per_item]
            for rec in recs:
                # Early year filtering
                year = rec.get("year")
                if year_min and year and year < year_min:
                    continue
                if year_max and year and year > year_max:
                    continue

                ids = rec.get("ids", {})
                simkl_id = ids.get("simkl")
                if not simkl_id or simkl_id in all_recs:
                    continue

                all_recs[simkl_id] = rec

                # Check if we need to fetch details (missing TMDB ID)
                if not ids.get("tmdb"):
                    needs_detail_fetch.append(simkl_id)

        logger.info(
            f"Collected {len(all_recs)} unique recommendations, " f"{len(needs_detail_fetch)} need detail fetch"
        )

        # Step 3: Fetch missing details (only for items without TMDB ID)
        if needs_detail_fetch:
            detail_tasks = [
                self._fetch_with_semaphore(self.get_item_details(simkl_id, mtype, api_key))
                for simkl_id in needs_detail_fetch
            ]
            fetched_details = await asyncio.gather(*detail_tasks, return_exceptions=True)

            for simkl_id, detail in zip(needs_detail_fetch, fetched_details):
                if isinstance(detail, Exception) or not detail:
                    continue
                # Update the rec with full details
                all_recs[simkl_id] = detail

        # Step 4: Normalize all items to TMDB format
        normalized = []
        for simkl_id, rec in all_recs.items():
            tmdb_id = rec.get("ids", {}).get("tmdb")
            if not tmdb_id:
                # Skip items we couldn't resolve to TMDB
                continue

            normalized_item = normalize_simkl_to_tmdb(rec, mtype)
            normalized.append(normalized_item)

        logger.info(f"Returning {len(normalized)} normalized Simkl recommendations")
        return normalized


simkl_service = SimklService()
