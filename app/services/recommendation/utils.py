from typing import Any

from loguru import logger

from app.services.recommendation.filtering import RecommendationFiltering, filter_items_by_settings
from app.services.recommendation.metadata import RecommendationMetadata


def content_type_to_mtype(content_type: str) -> str:
    return "tv" if content_type in ("tv", "series") else "movie"


async def resolve_tmdb_id(item_id: str, tmdb_service: Any) -> int | None:
    """Resolve item ID to TMDB ID.

    Handles formats: tmdb:123, tt123456, or plain integer.
    """
    if item_id.startswith("tmdb:"):
        try:
            return int(item_id.split(":")[1])
        except (ValueError, IndexError):
            return None
    elif item_id.startswith("tt"):
        tmdb_id, _ = await tmdb_service.find_by_imdb_id(item_id)
        return tmdb_id
    else:
        try:
            return int(item_id)
        except ValueError:
            return None


async def pad_to_min(
    content_type: str,
    existing: list[dict],
    min_items: int,
    tmdb_service: Any,
    user_settings: Any = None,
    watched_tmdb: set[int] | None = None,
    watched_imdb: set[str] | None = None,
) -> list[dict]:
    """Pad recommendations to meet minimum item count with trending/popular items."""
    need = max(0, int(min_items) - len(existing))
    if need <= 0:
        return existing

    watched_tmdb = watched_tmdb or set()
    watched_imdb = watched_imdb or set()
    excluded_ids = set(RecommendationFiltering.get_excluded_genre_ids(user_settings, content_type))

    mtype = content_type_to_mtype(content_type)
    pool: list[dict] = []

    try:
        tr = await tmdb_service.get_trending(mtype, time_window="week")
        pool.extend(tr.get("results", [])[:60])
        tr2 = await tmdb_service.get_top_rated(mtype)
        pool.extend(tr2.get("results", [])[:60])
    except Exception as e:
        logger.debug(f"Error fetching trending/top-rated for padding: {e}")
        return existing

    pool = filter_items_by_settings(pool, user_settings)

    existing_tmdb: set[int] = set()
    for it in existing:
        tid = it.get("_tmdb_id") or it.get("tmdb_id") or it.get("id")
        try:
            if isinstance(tid, str) and tid.startswith("tmdb:"):
                tid = int(tid.split(":")[1])
            existing_tmdb.add(int(tid))
        except Exception:
            pass

    dedup: dict[int, dict] = {}
    for it in pool:
        tid = it.get("id")
        if not tid or tid in existing_tmdb or tid in watched_tmdb:
            continue
        gids = it.get("genre_ids") or []
        if excluded_ids.intersection(gids):
            continue
        va = float(it.get("vote_average") or 0.0)
        vc = int(it.get("vote_count") or 0)
        if vc < 200 or va < 6.0:
            continue
        dedup[tid] = it
        if len(dedup) >= need * 3:
            break

    if not dedup:
        return existing

    meta = await RecommendationMetadata.fetch_batch(
        tmdb_service,
        list(dedup.values()),
        content_type,
        user_settings=user_settings,
    )

    extra: list[dict] = []
    for it in meta:
        if it.get("id") in watched_imdb:
            continue
        if it.get("_external_ids", {}).get("imdb_id") in watched_imdb:
            continue
        is_dup = any(e.get("id") == it.get("id") for e in existing)
        if is_dup:
            continue
        it.pop("_external_ids", None)
        extra.append(it)
        if len(extra) >= need:
            break

    return existing + extra
