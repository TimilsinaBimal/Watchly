from datetime import datetime
from typing import Any
from urllib.parse import unquote

from app.core.constants import DISCOVERY_SETTINGS
from app.core.settings import DEFAULT_YEAR_MIN, get_current_year
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
    """
    Handles exclusion sets, genre whitelists, and item filtering.
    """

    @staticmethod
    async def get_exclusion_sets(
        stremio_service: Any,
        library_data: LibraryCollection | None = None,
        auth_key: str | None = None,
    ) -> tuple[set[str], set[int]]:
        """Build exclusion sets for watched/loved content."""
        if library_data is None:
            if not auth_key:
                return set(), set()
            library_data = await stremio_service.library.get_library_items(auth_key)

        if library_data is None:
            return set(), set()

        all_items = library_data.all_items_with_removed()

        imdb_ids = set()
        tmdb_ids = set()

        for item in all_items:
            item_id = item.get("_id", "")
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
    def filter_candidates(
        candidates: list[dict[str, Any]], watched_imdb: set[str], watched_tmdb: set[int]
    ) -> list[dict[str, Any]]:
        """
        Filter candidates against watched sets.
        Matches both TMDB (int) and IMDB (str).
        """
        filtered = []
        for item in candidates:
            tid = item.get("id")
            # 1. Check TMDB ID (integer)
            if tid and isinstance(tid, int) and tid in watched_tmdb:
                continue

            # 2. Check Stremio ID (string) if present as 'id'
            if tid and isinstance(tid, str):
                if tid in watched_imdb:
                    continue
                if tid.startswith("tmdb:"):
                    try:
                        if int(tid.split(":")[1]) in watched_tmdb:
                            continue
                    except Exception:
                        pass

            # 3. Check External IDs
            ext = item.get("external_ids", {}) or item.get("_external_ids", {})
            imdb = ext.get("imdb_id")
            if imdb and imdb in watched_imdb:
                continue

            # 4. Handle cases where TMDB ID is in 'id' but it's a string
            try:
                if tid and int(tid) in watched_tmdb:
                    continue
            except Exception:
                pass

            filtered.append(item)
        return filtered

    @staticmethod
    def get_quality_thresholds(user_settings: Any) -> tuple[float, int]:
        """
        Get dynamic quality thresholds (min_rating, min_votes) based on popularity preference.
        """

        quality_rating_mapping = {
            "mainstream": (6.2, 500),  # (min_rating, min_votes)
            "balanced": (6.7, 250),
            "gems": (7.2, 100),
            "all": (5.0, 50),
        }
        if not user_settings:
            return quality_rating_mapping.get("balanced")

        pop_pref = getattr(user_settings, "popularity", "balanced")
        return quality_rating_mapping.get(pop_pref)

    @staticmethod
    def get_sort_by_preference(user_settings: Any) -> str:
        """
        Get optimal sort order based on popularity preference.
        """
        if not user_settings:
            return "popularity.desc"

        pop_pref = getattr(user_settings, "popularity", "balanced")

        if pop_pref == "gems":
            # For hidden gems, we want high quality first, not high popularity
            return "vote_average.desc"

        # For Mainstream/Balanced/All, popularity is the best proxy for "good suggestions"
        return "popularity.desc"

    @staticmethod
    def get_excluded_genre_ids(user_settings: Any, content_type: str) -> list[int]:
        """Get genre IDs to exclude based on user settings."""
        if not user_settings:
            return []
        if content_type == "movie":
            return [int(g) for g in user_settings.excluded_movie_genres]
        elif content_type in ["series", "tv"]:
            return [int(g) for g in user_settings.excluded_series_genres]
        return []


# --- Standalone filtering functions (moved from utils.py) ---


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


def build_discover_params(user_settings: Any) -> dict[str, Any]:
    """Build TMDB discover API parameters based on user settings."""
    params: dict[str, Any] = {}
    if not user_settings:
        return params

    current_date = datetime.now()
    current_year = get_current_year()

    year_min = getattr(user_settings, "year_min", DEFAULT_YEAR_MIN)
    year_max = getattr(user_settings, "year_max", current_year)

    for prefix in ["primary_release_date", "first_air_date"]:
        params[f"{prefix}.gte"] = f"{year_min}-01-01"
        if year_max >= current_year:
            params[f"{prefix}.lte"] = current_date.strftime("%Y-%m-%d")
        else:
            params[f"{prefix}.lte"] = f"{year_max}-12-31"

    return params


def apply_discover_filters(params: dict[str, Any], user_settings: Any) -> dict[str, Any]:
    """Merge discover params with global user settings (years, popularity)."""
    if not user_settings:
        return params

    global_params = build_discover_params(user_settings)
    params = {**global_params, **params}

    min_rating, min_votes = RecommendationFiltering.get_quality_thresholds(user_settings)

    if "vote_count.gte" not in params:
        params["vote_count.gte"] = min_votes
    if "vote_average.gte" not in params:
        params["vote_average.gte"] = min_rating

    return params


def filter_items_by_settings(
    items: list[dict[str, Any]], user_settings: Any, simkl: bool = False
) -> list[dict[str, Any]]:
    """Filter items post-fetch based on user settings (years, popularity)."""
    if not user_settings:
        return items

    year_min = getattr(user_settings, "year_min", DEFAULT_YEAR_MIN)
    year_max = getattr(user_settings, "year_max", get_current_year())
    pop_pref = getattr(user_settings, "popularity", "balanced")

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

        params = DISCOVERY_SETTINGS.get(pop_pref, {})
        if not params:
            continue

        ops = {
            "gte": lambda x, y: x >= y,
            "lte": lambda x, y: x <= y,
        }

        passes_all = True
        for param in params:
            t_param, param_ops = param.split(".")
            param_operator = ops.get(param_ops)
            if not param_operator:
                continue
            if simkl and t_param == "popularity":
                continue
            item_value = item.get(t_param)
            if item_value is None or not param_operator(item_value, params[param]):
                passes_all = False
                break

        if passes_all:
            filtered.append(item)

    return filtered
