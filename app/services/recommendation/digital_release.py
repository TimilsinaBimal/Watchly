"""Drops movies that cannot be watched at home yet.

A row full of titles still stuck in cinemas promises hours of "not out yet", so
this filter keeps only movies that TMDB already lists as available off the big
screen: digital, disc or broadcast. It runs opt-in during a row build and fails
open, so a missing or failed release-date lookup never hides a title for good.
Series are left alone: they air per episode, and TMDB home-release dates do not
apply to them the same way.
"""

import asyncio
from datetime import datetime, timezone
from typing import Any

from loguru import logger

from app.core.constants import DEFAULT_CONCURRENCY_LIMIT

# How long after any release a movie is assumed to be available at home without
# spending a release-date lookup on it. A year past its earliest premiere, a
# title without a home-edition date is treated as long out.
HOME_RELEASE_GRACE_DAYS = 365

# Extra candidates fetched when the filter is on so rows don't come back short
# after the post-scoring pass drops some of them.
HOME_RELEASE_FETCH_OVERFETCH = 2

# TMDB release-date types that mark a home release: 4 = digital, 5 = physical,
# 6 = tv broadcast. Types 1-3 are premieres and theatrical runs.
HOME_RELEASE_TYPES = frozenset({4, 5, 6})


def _parse_date(value: Any) -> datetime | None:
    """Parse a TMDB date string (YYYY-MM-DD) as UTC, or None."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def summarize_release_dates(payload: dict[str, Any] | None) -> tuple[datetime | None, datetime | None]:
    """Earliest release of any kind and earliest home release, across all countries."""
    earliest_any: datetime | None = None
    earliest_home: datetime | None = None

    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list):
        return None, None

    for country in results:
        if not isinstance(country, dict):
            continue
        for entry in country.get("release_dates") or []:
            if not isinstance(entry, dict):
                continue
            parsed = _parse_date(entry.get("release_date"))
            if parsed is None:
                continue
            if earliest_any is None or parsed < earliest_any:
                earliest_any = parsed
            try:
                release_type = int(entry.get("type"))
            except (TypeError, ValueError):
                continue
            if release_type in HOME_RELEASE_TYPES and (earliest_home is None or parsed < earliest_home):
                earliest_home = parsed

    return earliest_any, earliest_home


def has_home_release(earliest_any: datetime | None, earliest_home: datetime | None, now: datetime) -> bool:
    """Decide availability from the two summary dates, failing open.

    - Theatrical release a year ago or longer: available, no lookup needed.
    - No release of any kind yet: hidden — the whole point of the filter.
    - Home release already past: available.
    - Anything else, i.e. a recent theatrical release with no (or only a
      future) home date: hidden until TMDB gains the date.
    - No usable data at all: available, so one broken lookup never guts a row.
    """
    if earliest_any is not None and (now - earliest_any).days >= HOME_RELEASE_GRACE_DAYS:
        return True
    if earliest_any is None and earliest_home is None:
        return True
    if earliest_any is not None and earliest_any > now:
        return False
    if earliest_home is not None and earliest_home <= now:
        return True
    return False


def digital_release_filter_active(user_settings: Any, content_type: str, catalog_id: str) -> bool:
    """Whether a row build should drop movies without a home release."""
    if content_type != "movie" or not getattr(user_settings, "digital_release_only", False):
        return False
    # The rewatch row serves titles from the user's own history: they have
    # plainly been seen already, so their home availability is beside the point.
    return catalog_id != "watchly.rewatch"


def _likely_long_released(item: dict[str, Any], now: datetime) -> bool:
    """A movie from two calendar years back is safely past any theatrical window,
    so no release-date lookup is needed for it."""
    try:
        return int(str(item.get("releaseInfo"))[:4]) <= now.year - 2
    except (TypeError, ValueError):
        return False


def _tmdb_id_of(item: dict[str, Any]) -> int | None:
    """TMDB id of an enrichment meta, tolerating missing or stringified ids."""
    tid = item.get("_tmdb_id")
    if isinstance(tid, int):
        return tid
    if isinstance(tid, str) and tid.isdigit():
        return int(tid)
    raw = item.get("id")
    if isinstance(raw, str) and raw.startswith("tmdb:"):
        digits = raw.rsplit(":", 1)[1]
        if digits.isdigit():
            return int(digits)
    return None


async def filter_movies_without_home_release(
    items: list[dict[str, Any]], tmdb_service: Any, now: datetime | None = None
) -> list[dict[str, Any]]:
    """Keep series (anything not typed as a movie) and every movie already released at home.

    Order and duplicates are preserved; lookups run capped and batched so a
    long row doesn't stampede TMDB.
    """
    now = now or datetime.now(timezone.utc)
    semaphore = asyncio.Semaphore(DEFAULT_CONCURRENCY_LIMIT)

    async def keep(item: dict[str, Any]) -> bool:
        if item.get("type") != "movie":
            return True
        if _likely_long_released(item, now):
            return True
        tmdb_id = _tmdb_id_of(item)
        if tmdb_id is None:
            return True
        async with semaphore:
            try:
                payload = await tmdb_service.get_release_dates(tmdb_id)
            except Exception as e:
                logger.debug(f"Release dates for movie {tmdb_id} unavailable ({type(e).__name__}); keeping it")
                return True
        earliest_any, earliest_home = summarize_release_dates(payload)
        return has_home_release(earliest_any, earliest_home, now)

    verdicts = await asyncio.gather(*(keep(item) for item in items))
    return [item for item, keep_it in zip(items, verdicts) if keep_it]
