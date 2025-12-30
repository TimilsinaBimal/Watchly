import json

from app.core.settings import UserSettings
from app.services.profile.integration import ProfileIntegration
from app.services.redis_service import redis_service
from app.services.stremio.service import StremioBundle


def get_catalogs_from_config(
    user_settings: UserSettings, cat_id: str, default_name: str, default_movie: bool, default_series: bool
):
    catalogs = []
    config = next((c for c in user_settings.catalogs if c.id == cat_id), None)
    if not config or config.enabled:
        name = config.name if config and config.name else default_name
        enabled_movie = getattr(config, "enabled_movie", default_movie) if config else default_movie
        enabled_series = getattr(config, "enabled_series", default_series) if config else default_series

        if enabled_movie:
            catalogs.append({"type": "movie", "id": cat_id, "name": name, "extra": []})
        if enabled_series:
            catalogs.append({"type": "series", "id": cat_id, "name": name, "extra": []})
    return catalogs


async def cache_profile_and_watched_sets(
    token: str,
    content_type: str,
    integration_service: ProfileIntegration,
    library_items: dict,
    bundle: StremioBundle,
    auth_key: str,
):
    profile, watched_tmdb, watched_imdb = await integration_service.build_profile_from_library(
        library_items, content_type, bundle, auth_key
    )

    # Cache profile
    if profile:
        profile_key = f"watchly:profile:{token}:{content_type}"
        await redis_service.set(profile_key, profile.model_dump_json())

    watched_sets_key = f"watchly:watched_sets:{token}:{content_type}"
    watched_sets_data = {
        "watched_tmdb": list(watched_tmdb),
        "watched_imdb": list(watched_imdb),
    }
    await redis_service.set(watched_sets_key, json.dumps(watched_sets_data))


def get_config_id(catalog) -> str | None:
    catalog_id = catalog.get("id", "")
    if catalog_id.startswith("watchly.theme."):
        return "watchly.theme"
    if catalog_id.startswith("watchly.loved."):
        return "watchly.loved"
    if catalog_id.startswith("watchly.watched."):
        return "watchly.watched"
    return catalog_id
