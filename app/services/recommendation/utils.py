from typing import Any

from loguru import logger

from app.core.constants import DISCOVERY_SETTINGS
from app.services.recommendation.filtering import RecommendationFiltering
from app.services.recommendation.metadata import RecommendationMetadata


def content_type_to_mtype(content_type: str) -> str:
    return "tv" if content_type in ("tv", "series") else "movie"


async def resolve_tmdb_id(item_id: str, tmdb_service: Any) -> int | None:
    """
    Resolve item ID to TMDB ID.

    Handles various formats: tmdb:123, tt123456, or plain integer.

    Args:
        item_id: Item ID in various formats
        tmdb_service: TMDB service instance for IMDB lookups

    Returns:
        TMDB ID or None
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


def filter_watched_by_imdb(enriched: list[dict[str, Any]], watched_imdb: set[str]) -> list[dict[str, Any]]:
    """
    Filter enriched items by watched IMDB IDs.

    Checks both the item's 'id' field and '_external_ids.imdb_id' field.

    Args:
        enriched: List of enriched metadata items
        watched_imdb: Set of watched IMDB IDs

    Returns:
        Filtered list excluding watched items
    """
    final = []
    for item in enriched:
        if item.get("id") in watched_imdb:
            continue
        if item.get("_external_ids", {}).get("imdb_id") in watched_imdb:
            continue
        final.append(item)
    return final


def filter_by_genres(
    items: list[dict[str, Any]],
    watched_tmdb: set[int],
    whitelist: set[int] | None = None,
    excluded_ids: list[int] | None = None,
) -> list[dict[str, Any]]:
    """
    Filter items by genre whitelist and excluded genres.

    Args:
        items: List of candidate items
        watched_tmdb: Set of watched TMDB IDs to exclude
        whitelist: Optional genre whitelist
        excluded_ids: Optional list of excluded genre IDs

    Returns:
        Filtered list of items
    """
    whitelist = whitelist or set()
    excluded_ids = excluded_ids or []
    filtered = []

    for item in items:
        item_id = item.get("id")
        if not item_id or item_id in watched_tmdb:
            continue

        genre_ids = item.get("genre_ids", [])

        # Excluded genres check
        if excluded_ids and any(gid in excluded_ids for gid in genre_ids):
            continue

        filtered.append(item)

    return filtered


async def pad_to_min(
    content_type: str,
    existing: list[dict],
    min_items: int,
    tmdb_service: Any,
    user_settings: Any = None,
    watched_tmdb: set[int] | None = None,
    watched_imdb: set[str] | None = None,
) -> list[dict]:
    """
    Pad recommendations to meet minimum item count by fetching trending/popular items.

    Args:
        content_type: Content type (movie/series)
        existing: Existing recommendations
        min_items: Minimum number of items required
        tmdb_service: TMDB service instance
        user_settings: User settings (optional)
        watched_tmdb: Set of watched TMDB IDs (optional)
        watched_imdb: Set of watched IMDB IDs (optional)

    Returns:
        List of recommendations padded to min_items
    """
    need = max(0, int(min_items) - len(existing))
    if need <= 0:
        return existing

    # Use provided watched sets (or empty sets if not provided)
    watched_tmdb = watched_tmdb or set()
    watched_imdb = watched_imdb or set()
    excluded_ids = set(RecommendationFiltering.get_excluded_genre_ids(user_settings, content_type))

    mtype = content_type_to_mtype(content_type)
    pool = []

    try:
        tr = await tmdb_service.get_trending(mtype, time_window="week")
        pool.extend(tr.get("results", [])[:60])
        tr2 = await tmdb_service.get_top_rated(mtype)
        pool.extend(tr2.get("results", [])[:60])
    except Exception as e:
        logger.debug(f"Error fetching trending/top-rated for padding: {e}")
        return existing

    # Filter pool by user settings (years, popularity)
    pool = filter_items_by_settings(pool, user_settings)

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
        if vc < 200 or va < 6.0:
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


def build_discover_params(user_settings: Any) -> dict[str, Any]:
    """
    Build TMDB discover API parameters based on user settings.
    """
    params = {}
    if not user_settings:
        return params

    from datetime import datetime

    current_date = datetime.now()
    current_year = current_date.year

    # 1. Year Range
    year_min = getattr(user_settings, "year_min", 1970)
    year_max = getattr(user_settings, "year_max", current_year)

    # Apply to both movie and tv date fields for convenience in merging
    for prefix in ["primary_release_date", "first_air_date"]:
        params[f"{prefix}.gte"] = f"{year_min}-01-01"

        # If year_max is current year or greater, use today's date for 'lte'
        # relative to the current time.
        if year_max >= current_year:
            params[f"{prefix}.lte"] = current_date.strftime("%Y-%m-%d")
        else:
            params[f"{prefix}.lte"] = f"{year_max}-12-31"

    return params


def apply_discover_filters(params: dict[str, Any], user_settings: Any) -> dict[str, Any]:
    """
    Merge specific discover params with global user settings (years, popularity).
    """
    if not user_settings:
        return params

    global_params = build_discover_params(user_settings)

    params = {**global_params, **params}

    min_rating, min_votes = RecommendationFiltering.get_quality_thresholds(user_settings)

    # Apply dynamic thresholds if not overridden by stricter local params
    if "vote_count.gte" not in params:
        params["vote_count.gte"] = min_votes

    if "vote_average.gte" not in params:
        params["vote_average.gte"] = min_rating

    return params


def filter_items_by_settings(
    items: list[dict[str, Any]], user_settings: Any, simkl: bool = False
) -> list[dict[str, Any]]:
    """
    Filter items post-fetch based on global user settings (years, popularity).
    Used for items from recommendations/similar APIs that don't support early filtering.
    """
    if not user_settings:
        return items

    year_min = getattr(user_settings, "year_min", 1970)
    year_max = getattr(user_settings, "year_max", 2026)
    pop_pref = getattr(user_settings, "popularity", "balanced")

    filtered = []

    for item in items:
        # 1. Year Filtering
        release_date = item.get("release_date") or item.get("first_air_date") or item.get("released")
        if release_date:
            try:
                year = int(release_date.split("-")[0])
                if year < year_min or year > year_max:
                    continue
            except (ValueError, IndexError):
                pass

        params = DISCOVERY_SETTINGS.get(pop_pref, {})
        if not params:
            continue

        # determine operations
        ops = {
            "gte": lambda x, y: x >= y,
            "lte": lambda x, y: x <= y,
        }

        passes_all_checks = True
        for param in params:
            t_param, param_ops = param.split(".")
            param_operator = ops.get(param_ops)
            if not param_operator:
                continue

            # skip popularity params if simkl
            if simkl and t_param == "popularity":
                continue

            item_value = item.get(t_param)
            if item_value is None or not param_operator(item_value, params[param]):
                passes_all_checks = False
                break

        if passes_all_checks:
            filtered.append(item)

    return filtered
