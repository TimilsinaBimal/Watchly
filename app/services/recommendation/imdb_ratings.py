import asyncio
import math
import re
from typing import Any

import httpx

from app.core.base_client import BaseClient
from app.core.constants import DEFAULT_CONCURRENCY_LIMIT


async def filter_by_imdb_rating(
    metas: list[dict[str, Any]], content_type: str, minimum: float | None
) -> list[dict[str, Any]]:
    if minimum is None or not metas:
        return metas

    client = BaseClient(base_url="https://v3-cinemeta.strem.io")
    semaphore = asyncio.Semaphore(DEFAULT_CONCURRENCY_LIMIT)

    async def rated_meta(meta: dict[str, Any]) -> dict[str, Any] | None:
        imdb_id = meta.get("imdb_id") or meta.get("id") or ""
        if not re.fullmatch(r"tt\d+", imdb_id):
            return None
        async with semaphore:
            try:
                response = await client.get(f"/meta/{content_type}/{imdb_id}.json")
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    return None
                raise
        raw_rating = (response.get("meta") or {}).get("imdbRating")
        try:
            rating = float(raw_rating)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(rating) or not 0 <= rating <= 10 or rating < minimum:
            return None
        # The existing imdbRating field contains TMDB votes until replaced here.
        return {**meta, "imdbRating": str(rating)}

    try:
        # Wait for all requests before closing their shared client, even on failure.
        results = await asyncio.gather(*(rated_meta(meta) for meta in metas), return_exceptions=True)
        for result in results:
            if isinstance(result, BaseException):
                raise result
        return [meta for meta in results if meta is not None]
    finally:
        await client.close()
