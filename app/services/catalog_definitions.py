import asyncio
import random
from datetime import datetime, timezone
from typing import Any, cast

from loguru import logger

from app.core.constants import DISCOVER_ONLY_EXTRA
from app.core.settings import CatalogConfig, UserSettings
from app.models.library import LibraryCollection
from app.services.profile.service import ProfileService
from app.services.row_generator import RowGeneratorService
from app.services.tmdb.service import get_tmdb_service
from app.services.user_cache import user_cache


def get_catalogs_from_config(
    user_settings: UserSettings,
    cat_id: str,
    default_name: str,
    default_movie: bool,
    default_series: bool,
) -> list[dict[str, Any]]:
    catalogs = []
    config = next((c for c in user_settings.catalogs if c.id == cat_id), None)

    if config and config.enabled:
        name = config.name if config.name else default_name
        enabled_movie = getattr(config, "enabled_movie", default_movie)
        enabled_series = getattr(config, "enabled_series", default_series)
        display_at_home = getattr(config, "display_at_home", True)
        extra = DISCOVER_ONLY_EXTRA if not display_at_home else []

        if enabled_movie:
            catalogs.append({"type": "movie", "id": cat_id, "name": name, "extra": extra})
        if enabled_series:
            catalogs.append({"type": "series", "id": cat_id, "name": name, "extra": extra})

    return catalogs


def get_config_id(catalog: dict[str, Any]) -> str | None:
    catalog_id = catalog.get("id", "")
    if catalog_id.startswith("watchly.theme."):
        return "watchly.theme"
    if catalog_id.startswith("watchly.loved."):
        return "watchly.loved"
    if catalog_id.startswith("watchly.watched."):
        return "watchly.watched"
    return catalog_id


def sort_catalogs(catalogs: list[dict[str, Any]], user_settings: UserSettings) -> list[dict[str, Any]]:
    """Sort catalogs according to user settings and content-type order."""
    if not user_settings:
        return catalogs

    order_map = {c.id: i for i, c in enumerate(user_settings.catalogs)}

    def get_setting_index(catalog: dict[str, Any]) -> int:
        config_id = get_config_id(catalog)
        if config_id is None:
            return 999
        return order_map.get(config_id, 999)

    sorting_order = getattr(user_settings, "sorting_order", "default")

    if sorting_order == "movies_first":
        return sorted(
            catalogs,
            key=lambda x: (
                0 if x.get("type") == "movie" else 1,
                get_setting_index(x),
            ),
        )

    if sorting_order == "series_first":
        return sorted(
            catalogs,
            key=lambda x: (
                0 if x.get("type") == "series" else 1,
                get_setting_index(x),
            ),
        )

    return sorted(catalogs, key=get_setting_index)


class DynamicCatalogService:
    """Generates catalog definitions from user history and settings."""

    def __init__(self, language: str = "en-US", tmdb_api_key: str | None = None):
        self.language = language
        self.tmdb_api_key = tmdb_api_key
        tmdb_service = get_tmdb_service(language=language, api_key=tmdb_api_key)
        self.profile_service = ProfileService(language=language, tmdb_api_key=tmdb_api_key)
        self.row_generator = RowGeneratorService(tmdb_service=tmdb_service)

    @staticmethod
    def normalize_type(type_: str) -> str:
        return "series" if type_ == "tv" else type_

    def build_catalog_entry(
        self,
        item,
        label: str,
        config_id: str,
        display_at_home: bool = True,
    ) -> dict[str, Any]:
        from app.models.library import StremioLibraryItem

        # Support both typed items and raw dicts
        if isinstance(item, StremioLibraryItem):
            item_id = item.id
            item_type = item.type
            item_name = item.name
        else:
            item_id = item.get("_id", "")
            item_type = item.get("type", "")
            item_name = item.get("name", "")

        if config_id in ["watchly.item", "watchly.loved", "watchly.watched"]:
            catalog_id = f"{config_id}.{item_id}"
        elif item_id.startswith("tt") and config_id in [
            "watchly.loved",
            "watchly.watched",
        ]:
            catalog_id = f"{config_id}.{item_id}"
        else:
            catalog_id = item_id

        extra = DISCOVER_ONLY_EXTRA if not display_at_home else []
        return {
            "type": self.normalize_type(item_type),
            "id": catalog_id,
            "name": f"{label} {item_name}",
            "extra": extra,
        }

    async def get_dynamic_catalogs(
        self,
        library_items: LibraryCollection,
        user_settings: UserSettings | None = None,
        token: str | None = None,
    ) -> list[dict[str, Any]]:
        """Generate all dynamic catalog rows based on enabled configurations."""
        catalogs: list[dict[str, Any]] = []
        if not user_settings:
            return catalogs

        theme_cfg, loved_cfg, watched_cfg = self._resolve_catalog_configs(user_settings)

        if theme_cfg and theme_cfg.enabled:
            enabled_movie = getattr(theme_cfg, "enabled_movie", True)
            enabled_series = getattr(theme_cfg, "enabled_series", True)
            display_at_home = getattr(theme_cfg, "display_at_home", True)
            theme_catalogs = await self._build_theme_catalogs(
                library_items,
                user_settings,
                enabled_movie,
                enabled_series,
                display_at_home,
                token,
            )
            catalogs.extend(theme_catalogs)

        for mtype in ["movie", "series"]:
            await self._add_item_based_rows(catalogs, library_items, mtype, loved_cfg, watched_cfg)

        catalogs.extend(get_catalogs_from_config(user_settings, "watchly.rec", "Top Picks for You", True, True))
        catalogs.extend(
            get_catalogs_from_config(
                user_settings,
                "watchly.creators",
                "From your favourite Creators",
                False,
                False,
            )
        )
        catalogs.extend(
            get_catalogs_from_config(
                user_settings,
                "watchly.all.loved",
                "Based on what you loved",
                True,
                True,
            )
        )
        catalogs.extend(
            get_catalogs_from_config(
                user_settings,
                "watchly.liked.all",
                "Based on what you liked",
                True,
                True,
            )
        )

        return catalogs

    # --- Theme catalog building (was ThemeCatalogService) ---

    async def _build_theme_catalogs(
        self,
        library_items: LibraryCollection,
        user_settings: UserSettings | None,
        enabled_movie: bool,
        enabled_series: bool,
        display_at_home: bool,
        token: str | None,
    ) -> list[dict[str, Any]]:
        gemini_api_key = user_settings.gemini_api_key if user_settings else None

        tasks = []
        if enabled_movie:
            tasks.append(self._build_theme_rows_for_type(library_items, "movie", gemini_api_key, token))
        if enabled_series:
            tasks.append(self._build_theme_rows_for_type(library_items, "series", gemini_api_key, token))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        catalogs: list[dict[str, Any]] = []
        extra = DISCOVER_ONLY_EXTRA if not display_at_home else []

        for result in results:
            if not isinstance(result, tuple):
                continue
            media_type, rows = cast(tuple[str, list[Any]], result)
            for row in rows:
                catalogs.append(
                    {
                        "type": media_type,
                        "id": row.id,
                        "name": row.title,
                        "extra": extra,
                    }
                )

        return catalogs

    async def _build_theme_rows_for_type(
        self,
        library_items: LibraryCollection,
        media_type: str,
        gemini_api_key: str | None,
        token: str | None,
    ) -> tuple[str, list[Any]]:
        logger.info(f"[Theme Catalogs] Building rows for {media_type}")

        # Try cached profile first, build fresh if missing
        profile = None
        if token:
            profile = await user_cache.get_profile(token, media_type)

        if not profile:
            profile, _, _ = await self.profile_service.build_profile_from_library(library_items, media_type, None, None)

        if not profile:
            logger.warning(f"Failed to build profile for {media_type}")
            return media_type, []

        rows = await self.row_generator.generate_rows(profile, media_type, api_key=gemini_api_key)
        return media_type, rows

    # --- Item-based rows ---

    def _resolve_catalog_configs(self, user_settings: UserSettings) -> tuple[Any, Any, Any]:
        cfg_map = {c.id: c for c in user_settings.catalogs}
        theme = cfg_map.get("watchly.theme")
        loved = cfg_map.get("watchly.loved")
        watched = cfg_map.get("watchly.watched")

        if not loved and not watched:
            old_item = cfg_map.get("watchly.item")
            if old_item and old_item.enabled:
                loved = CatalogConfig(id="watchly.loved", name=None, enabled=True)
                watched = CatalogConfig(id="watchly.watched", name=None, enabled=True)

        return theme, loved, watched

    def _parse_item_last_watched(self, item) -> datetime:
        from app.models.library import StremioLibraryItem

        if isinstance(item, StremioLibraryItem):
            if item.state.lastWatched:
                return item.state.lastWatched
            if item.mtime:
                try:
                    return datetime.fromisoformat(str(item.mtime).replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    pass
            return datetime.min.replace(tzinfo=timezone.utc)

        # Fallback for raw dicts
        val = item.get("state", {}).get("lastWatched")
        if val:
            try:
                if isinstance(val, str):
                    return datetime.fromisoformat(val.replace("Z", "+00:00"))
                return val
            except (ValueError, TypeError):
                pass

        val = item.get("_mtime")
        if val:
            try:
                return datetime.fromisoformat(str(val).replace("Z", "+00:00"))
            except (ValueError, TypeError):
                pass
        return datetime.min.replace(tzinfo=timezone.utc)

    async def _add_item_based_rows(
        self,
        catalogs: list[dict[str, Any]],
        library_items: LibraryCollection,
        content_type: str,
        loved_config: Any,
        watched_config: Any,
    ) -> None:
        def is_type_enabled(config: Any, ct: str) -> bool:
            if not config:
                return False
            if ct == "movie":
                return getattr(config, "enabled_movie", True)
            if ct == "series":
                return getattr(config, "enabled_series", True)
            return True

        last_loved = None
        if loved_config and loved_config.enabled and is_type_enabled(loved_config, content_type):
            loved = [i for i in library_items.loved if i.type == content_type]
            loved.sort(key=self._parse_item_last_watched, reverse=True)
            last_loved = random.choice(loved[:3]) if loved else None
            if last_loved:
                label = loved_config.name if loved_config.name else "More like"
                display_at_home = getattr(loved_config, "display_at_home", True)
                catalogs.append(self.build_catalog_entry(last_loved, label, "watchly.loved", display_at_home))

        if watched_config and watched_config.enabled and is_type_enabled(watched_config, content_type):
            watched = [i for i in library_items.watched if i.type == content_type]
            watched.sort(key=self._parse_item_last_watched, reverse=True)

            if last_loved:
                watched = [i for i in watched if i.id != last_loved.id]

            last_watched = random.choice(watched[:3]) if watched else None
            if last_watched:
                label = watched_config.name if watched_config.name else "Because you watched"
                display_at_home = getattr(watched_config, "display_at_home", True)
                catalogs.append(
                    self.build_catalog_entry(
                        last_watched,
                        label,
                        "watchly.watched",
                        display_at_home,
                    )
                )
