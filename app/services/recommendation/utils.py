"""
Utility functions for recommendations.
"""

from typing import Any

from loguru import logger

from app.services.recommendation.filtering import RecommendationFiltering
from app.services.recommendation.metadata import RecommendationMetadata


async def pad_to_min(
    content_type: str,
    existing: list[dict],
    min_items: int,
    tmdb_service: Any,
    user_settings: Any = None,
    stremio_service: Any = None,
    library_data: dict | None = None,
    auth_key: str | None = None,
) -> list[dict]:
    """
    Pad recommendations to meet minimum item count by fetching trending/popular items.

    Args:
        content_type: Content type (movie/series)
        existing: Existing recommendations
        min_items: Minimum number of items required
        tmdb_service: TMDB service instance
        user_settings: User settings (optional)
        stremio_service: Stremio service (optional, for watched sets)
        library_data: Library data (optional, for watched sets)
        auth_key: Auth key (optional, for watched sets)

    Returns:
        List of recommendations padded to min_items
    """
    need = max(0, int(min_items) - len(existing))
    if need <= 0:
        return existing

    # Get watched sets and excluded genres
    watched_imdb, watched_tmdb = await RecommendationFiltering.get_exclusion_sets(
        stremio_service, library_data, auth_key
    )
    excluded_ids = set(RecommendationFiltering.get_excluded_genre_ids(user_settings, content_type))

    mtype = "tv" if content_type in ("tv", "series") else "movie"
    pool = []

    try:
        tr = await tmdb_service.get_trending(mtype, time_window="week")
        pool.extend(tr.get("results", [])[:60])
        tr2 = await tmdb_service.get_top_rated(mtype)
        pool.extend(tr2.get("results", [])[:60])
    except Exception as e:
        logger.debug(f"Error fetching trending/top-rated for padding: {e}")
        return existing

    # Get existing TMDB IDs
    existing_tmdb = set()
    for it in existing:
        tid = it.get("_tmdb_id") or it.get("tmdb_id") or it.get("id")
        try:
            if isinstance(tid, str) and tid.startswith("tmdb:"):
                tid = int(tid.split(":")[1])
            existing_tmdb.add(int(tid))
        except Exception:
            pass

    # Filter pool
    dedup = {}
    for it in pool:
        tid = it.get("id")
        if not tid or tid in existing_tmdb or tid in watched_tmdb:
            continue
        gids = it.get("genre_ids") or []
        if excluded_ids.intersection(gids):
            continue

        # Quality threshold
        va, vc = float(it.get("vote_average") or 0.0), int(it.get("vote_count") or 0)
        if vc < 100 or va < 6.2:
            continue
        dedup[tid] = it
        if len(dedup) >= need * 3:
            break

    if not dedup:
        return existing

    # Enrich metadata
    meta = await RecommendationMetadata.fetch_batch(
        tmdb_service,
        list(dedup.values()),
        content_type,
        target_count=need * 2,
        user_settings=user_settings,
    )

    # Add to existing, filtering watched items
    extra = []
    for it in meta:
        if it.get("id") in watched_imdb:
            continue
        if it.get("_external_ids", {}).get("imdb_id") in watched_imdb:
            continue

        # Final check against existing
        is_dup = False
        for e in existing:
            if e.get("id") == it.get("id"):
                is_dup = True
                break
        if is_dup:
            continue

        it.pop("_external_ids", None)
        extra.append(it)
        if len(extra) >= need:
            break

    return existing + extra
