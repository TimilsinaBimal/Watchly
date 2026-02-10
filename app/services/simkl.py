import asyncio
from typing import Any

from cachetools import TTLCache
from httpx import AsyncClient
from loguru import logger


def get_popularity(rank: int, N: int = 100000, K: int = 100) -> float:
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
        self.client = AsyncClient(timeout=10)
        self._semaphore = asyncio.Semaphore(10)  # Max 10 concurrent requests
        self._details_cache: TTLCache = TTLCache(maxsize=1000, ttl=3600)  # Cache up to 1000 items  # 1 hour TTL

    async def _fetch_with_semaphore(self, coro):
        """Execute a coroutine with semaphore for rate limiting."""
        async with self._semaphore:
            return await coro

    async def get_trending(self, api_key: str):
        url = f"{self.base_url}/movies/trending"
        params = {"client_id": api_key}
        try:
            response = await self.client.get(url, params=params, follow_redirects=True)
            response.raise_for_status()
            json_response = response.json()
            # convert rank to tmdb popularity scale
            json_response["popularity"] = get_popularity(json_response.get("rank"))
            return json_response

        except Exception as e:
            logger.error(f"Error fetching details from Simkl: {e}")
            return []

    async def get_item_details(self, simkl_id, mtype: str, api_key: str) -> dict[str, Any]:
        """Fetch full item details from Simkl with caching."""
        # Create cache key
        cache_key = f"{simkl_id}:{mtype}"

        # Check cache first
        if cache_key in self._details_cache:
            logger.debug(f"Cache hit for Simkl item {simkl_id}")
            return self._details_cache[cache_key]

        # Fetch from API
        mtype_path = "movies" if mtype == "movie" else "tv"
        url = f"{self.base_url}/{mtype_path}/{simkl_id}"
        params = {"client_id": api_key, "extended": "full"}
        try:
            response = await self.client.get(url, params=params, follow_redirects=True)
            response.raise_for_status()
            result = response.json()

            # Store in cache
            self._details_cache[cache_key] = result
            return result

        except Exception as e:
            logger.error(f"Error fetching details from Simkl: {e}")
            return {}

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
