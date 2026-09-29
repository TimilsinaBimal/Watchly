from datetime import datetime
from typing import Any
from urllib.parse import unquote

from app.core.constants import DISCOVERY_SETTINGS
from app.core.settings import UserSettings, get_current_year
from app.models.library import LibraryCollection


def parse_identifier(identifier: str) -> tuple[str | None, int | None]:
    """Parse Stremio identifier to extract IMDB ID and TMDB ID."""
    if not identifier:
        return None, None

    decoded = unquote(identifier)
    imdb_id: str | None = None
    tmdb_id: int | None = None

    for token in decoded.split(","):
        token = token.strip()
        if not token:
            continue
        if token.startswith("tt") and imdb_id is None:
            imdb_id = token
        elif token.startswith("tmdb:") and tmdb_id is None:
            try:
                tmdb_id = int(token.split(":", 1)[1])
            except (ValueError, IndexError):
                continue
        if imdb_id and tmdb_id is not None:
            break

    return imdb_id, tmdb_id


class RecommendationFiltering:
    """Handles exclusion sets, genre whitelists, and item filtering."""

    @staticmethod
    def get_exclusion_sets(library_data: LibraryCollection) -> tuple[set[str], set[int]]:
        """Build exclusion sets for watched/loved content."""
        imdb_ids = set()
        tmdb_ids = set()

        for item in library_data.all_items():
            item_id = item.id
            if not item_id:
                continue

            imdb_id, tmdb_id = parse_identifier(item_id)

            if imdb_id:
                imdb_ids.add(imdb_id)
            if tmdb_id:
                tmdb_ids.add(tmdb_id)

            # Fallback parsing for common Stremio/Watchly patterns
            if item_id.startswith("tt"):
                # Handle tt123 and tt123:1:1
                base_imdb = item_id.split(":")[0]
                imdb_ids.add(base_imdb)
            elif item_id.startswith("tmdb:"):
                try:
                    tid = int(item_id.split(":")[1])
                    tmdb_ids.add(tid)
                except Exception:
                    pass

        return imdb_ids, tmdb_ids

    @staticmethod
    def get_quality_thresholds(user_settings: UserSettings) -> tuple[float, int]:
        """(min_rating, min_votes) for the user's popularity preference."""
        band = DISCOVERY_SETTINGS[user_settings.popularity]
        return band["vote_average.gte"], band["vote_count.gte"]

    @staticmethod
    def get_sort_by_preference(user_settings: UserSettings) -> str:
        if user_settings.popularity == "gems":
            # For hidden gems, we want high quality first, not high popularity
            return "vote_average.desc"

        # For Mainstream/Balanced/All, popularity is the best proxy for "good suggestions"
        return "popularity.desc"

    @staticmethod
    def get_excluded_genre_ids(user_settings: UserSettings, content_type: str) -> list[int]:
        if content_type == "movie":
            return [int(g) for g in user_settings.excluded_movie_genres]
        elif content_type in ["series", "tv"]:
            return [int(g) for g in user_settings.excluded_series_genres]
        return []


def filter_watched_by_imdb(enriched: list[dict[str, Any]], watched_imdb: set[str]) -> list[dict[str, Any]]:
    """Filter enriched items by watched IMDB IDs."""
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
    excluded_ids: list[int] | None = None,
) -> list[dict[str, Any]]:
    """Filter items by watched set and excluded genres."""
    excluded_ids = excluded_ids or []
    filtered = []

    for item in items:
        item_id = item.get("id")
        if not item_id or item_id in watched_tmdb:
            continue
        genre_ids = item.get("genre_ids", [])
        if excluded_ids and any(gid in excluded_ids for gid in genre_ids):
            continue
        filtered.append(item)

    return filtered


def build_discover_params(user_settings: UserSettings) -> dict[str, Any]:
    """Build TMDB discover API parameters based on user settings."""
    params: dict[str, Any] = {}
    current_date = datetime.now()
    current_year = get_current_year()
    year_min = user_settings.year_min
    year_max = user_settings.year_max

    for prefix in ["primary_release_date", "first_air_date"]:
        params[f"{prefix}.gte"] = f"{year_min}-01-01"
        if year_max >= current_year:
            params[f"{prefix}.lte"] = current_date.strftime("%Y-%m-%d")
        else:
            params[f"{prefix}.lte"] = f"{year_max}-12-31"

    return params


# DISCOVERY_SETTINGS keys TMDB /discover can actually filter on. popularity.* is
# deliberately excluded — TMDB has no popularity filter, so those gates run
# post-fetch only (see filter_items_by_settings).
TMDB_DISCOVER_FILTER_KEYS = {"vote_count.gte", "vote_count.lte", "vote_average.gte", "vote_average.lte"}


def apply_discover_filters(params: dict[str, Any], user_settings: UserSettings) -> dict[str, Any]:
    """Merge discover params with global user settings (years, quality band)."""
    params = {**build_discover_params(user_settings), **params}
    for key, value in DISCOVERY_SETTINGS[user_settings.popularity].items():
        if key in TMDB_DISCOVER_FILTER_KEYS:
            params.setdefault(key, value)

    return params


def filter_items_by_settings(
    items: list[dict[str, Any]], user_settings: UserSettings, apply_quality_band: bool = True
) -> list[dict[str, Any]]:
    """Filter items post-fetch: year window always, plus the DISCOVERY_SETTINGS
    quality/reach band when apply_quality_band.

    Simkl candidates pass apply_quality_band=False: their vote_count is often a flat
    default and their popularity is estimated from rank, so the TMDB-calibrated band
    would drop them on noise. They arrive already year-filtered by Simkl, and their
    popularity/quality still feed scoring downstream.
    """
    year_min = user_settings.year_min
    year_max = user_settings.year_max
    params = DISCOVERY_SETTINGS[user_settings.popularity] if apply_quality_band else {}

    ops = {
        "gte": lambda x, y: x >= y,
        "lte": lambda x, y: x <= y,
    }

    filtered = []
    for item in items:
        release_date = item.get("release_date") or item.get("first_air_date") or item.get("released")
        if release_date:
            try:
                year = int(release_date.split("-")[0])
                if year < year_min or year > year_max:
                    continue
            except (ValueError, IndexError):
                pass

        passes_all = True
        for param in params:
            t_param, param_ops = param.split(".")
            param_operator = ops.get(param_ops)
            if not param_operator:
                continue
            item_value = item.get(t_param)
            if item_value is None or not param_operator(item_value, params[param]):
                passes_all = False
                break

        if passes_all:
            filtered.append(item)

    return filtered
