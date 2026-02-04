from typing import Any

from app.core.constants import DISCOVER_ONLY_EXTRA
from app.core.settings import UserSettings
from app.services.profile.integration import ProfileIntegration
from app.services.stremio.service import StremioBundle
from app.services.user_cache import user_cache


def get_catalogs_from_config(
    user_settings: UserSettings,
    cat_id: str,
    default_name: str,
    default_movie: bool,
    default_series: bool,
):
    catalogs = []
    config = next((c for c in user_settings.catalogs if c.id == cat_id), None)

    if config and config.enabled:
        name = config.name if config and config.name else default_name
        enabled_movie = getattr(config, "enabled_movie", default_movie) if config else default_movie
        enabled_series = getattr(config, "enabled_series", default_series) if config else default_series
        display_at_home = getattr(config, "display_at_home", True) if config else True

        extra = DISCOVER_ONLY_EXTRA if not display_at_home else []

        if enabled_movie:
            catalogs.append({"type": "movie", "id": cat_id, "name": name, "extra": extra})
        if enabled_series:
            catalogs.append({"type": "series", "id": cat_id, "name": name, "extra": extra})
    return catalogs


async def cache_profile_and_watched_sets(
    token: str,
    content_type: str,
    integration_service: ProfileIntegration,
    library_items: dict,
    bundle: StremioBundle,
    auth_key: str,
):
    """
    Build and cache profile and watched sets for a user and content type.
    Uses the centralized UserCacheService for caching.
    """
    (
        profile,
        watched_tmdb,
        watched_imdb,
    ) = await integration_service.build_profile_incremental(library_items, content_type, token, bundle, auth_key)

    await user_cache.set_profile_and_watched_sets(token, content_type, profile, watched_tmdb, watched_imdb)
    return profile, watched_tmdb, watched_imdb


def get_config_id(catalog) -> str | None:
    catalog_id = catalog.get("id", "")
    if catalog_id.startswith("watchly.theme."):
        return "watchly.theme"
    if catalog_id.startswith("watchly.loved."):
        return "watchly.loved"
    if catalog_id.startswith("watchly.watched."):
        return "watchly.watched"
    return catalog_id


def sort_catalogs(catalogs: list[dict[str, Any]], user_settings: UserSettings) -> list[dict[str, Any]]:
    """
    Sort catalogs according to user settings and sorting order choice.

    Sorting Orders:
    - default: Interleaved (by category priority, then movie then series)
    - movies_first: Group all movies first, then all series
    - series_first: Group all series first, then all movies
    """
    if not user_settings:
        return catalogs

    # Get the original order index from user settings for each catalog category
    order_map = {c.id: i for i, c in enumerate(user_settings.catalogs)}

    # Base sorting key: setting index (priority)
    def get_setting_index(cat):
        return order_map.get(get_config_id(cat), 999)

    sorting_order = getattr(user_settings, "sorting_order", "default")

    if sorting_order == "movies_first":
        # Group movies first, then series
        # movies: type_priority=0, series: type_priority=1
        sorted_catalogs = sorted(catalogs, key=lambda x: (0 if x.get("type") == "movie" else 1, get_setting_index(x)))
    elif sorting_order == "series_first":
        # Group series first, then movies
        # series: type_priority=0, movies: type_priority=1
        sorted_catalogs = sorted(catalogs, key=lambda x: (0 if x.get("type") == "series" else 1, get_setting_index(x)))
    else:
        # Default: Interleaved (by category priority)
        # Python's sorted is stable, preserving movie then series within same priority
        sorted_catalogs = sorted(catalogs, key=get_setting_index)

    return sorted_catalogs
