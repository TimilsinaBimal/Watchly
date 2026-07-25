import asyncio
import random
from datetime import datetime, timezone
from typing import Any, cast

from loguru import logger

from app.core.constants import DISCOVER_ONLY_EXTRA
from app.core.settings import CatalogConfig, LLMConfig, UserSettings, resolve_llm_config
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
    if catalog_id.startswith("watchly.item."):
        return "watchly.item"
    # Legacy stored manifests still emit watchly.loved.* / watchly.watched.* —
    # map them to the unified watchly.item config so user ordering keeps working.
    if catalog_id.startswith("watchly.loved.") or catalog_id.startswith("watchly.watched."):
        return "watchly.item"
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

        if config_id == "watchly.item":
            catalog_id = f"{config_id}.{item_id}"
        else:
            catalog_id = item_id

        # External-source items (Trakt/Simkl) and partial Stremio entries
        # occasionally lack a title; without this guard the row renders as
        # "Because you loved " with a trailing space, which Stremio shows as
        # an empty catalog name.
        suffix = (item_name or "").strip() or "this title"
        extra = DISCOVER_ONLY_EXTRA if not display_at_home else []
        return {
            "type": self.normalize_type(item_type),
            "id": catalog_id,
            "name": f"{label} {suffix}",
            "_catalog_name_prefix": label,
            "_catalog_name_suffix": suffix,
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

        theme_cfg, item_cfg = self._resolve_catalog_configs(user_settings)

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
            await self._add_item_based_rows(catalogs, library_items, mtype, item_cfg)

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
        llm_config = resolve_llm_config(user_settings)

        tasks = []
        if enabled_movie:
            tasks.append(self._build_theme_rows_for_type(library_items, "movie", llm_config, token, user_settings))
        if enabled_series:
            tasks.append(self._build_theme_rows_for_type(library_items, "series", llm_config, token, user_settings))

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
        llm_config: LLMConfig | None,
        token: str | None,
        user_settings: UserSettings | None = None,
    ) -> tuple[str, list[Any]]:
        logger.info(f"[Theme Catalogs] Building rows for {media_type}")

        # Try cached profile first, build fresh if missing (honors watch_history_source).
        profile = None
        if token:
            profile = await user_cache.get_profile(token, media_type)

        if not profile:
            if token:
                profile, _, _ = await self.profile_service.build_and_cache_profile(
                    token, media_type, library_items, None, None, user_settings=user_settings
                )
            else:
                profile, _, _ = await self.profile_service.build_profile_from_library(
                    library_items, media_type, None, None
                )

        if not profile:
            logger.warning(f"Failed to build profile for {media_type}")
            return media_type, []

        rows = await self.row_generator.generate_rows(profile, media_type, llm_config=llm_config)
        return media_type, rows

    # --- Item-based rows ---

    def _resolve_catalog_configs(self, user_settings: UserSettings) -> tuple[Any, Any]:
        cfg_map = {c.id: c for c in user_settings.catalogs}
        theme = cfg_map.get("watchly.theme")
        item = cfg_map.get("watchly.item")

        # Legacy migration: users created before the loved/watched merge still
        # have separate `watchly.loved` and `watchly.watched` entries in their
        # saved settings. Synthesize a watchly.item config from whichever is
        # present so they don't lose the catalog on first load after the
        # upgrade. Donor preference: loved over watched (loved was opt-in
        # branded as the more intentional signal).
        if not item:
            legacy_loved = cfg_map.get("watchly.loved")
            legacy_watched = cfg_map.get("watchly.watched")
            donor = legacy_loved or legacy_watched
            if donor:
                enabled = bool((legacy_loved and legacy_loved.enabled) or (legacy_watched and legacy_watched.enabled))
                item = CatalogConfig(
                    id="watchly.item",
                    name="Because you Watched/Loved",
                    enabled=enabled,
                    enabled_movie=getattr(donor, "enabled_movie", True),
                    enabled_series=getattr(donor, "enabled_series", True),
                    display_at_home=getattr(donor, "display_at_home", True),
                    shuffle=getattr(donor, "shuffle", False),
                )

        return theme, item

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
        item_config: Any,
    ) -> None:
        """Emit one item-based row per content type.

        Seed selection: take the 3 most-recent loved items and the 3 most-recent
        watched items, combine, and pick uniformly at random. The label
        ("Because you loved X" vs "Because you watched X") follows the bucket
        the chosen seed came from. The configured `name` is for the FE display
        only — the served catalog title is always one of the two dynamic
        labels — so the configure page disables renaming this catalog.
        """
        if not item_config or not item_config.enabled:
            return

        if content_type == "movie" and not getattr(item_config, "enabled_movie", True):
            return
        if content_type == "series" and not getattr(item_config, "enabled_series", True):
            return

        loved = [i for i in library_items.loved if i.type == content_type]
        watched = [i for i in library_items.watched if i.type == content_type]
        loved.sort(key=self._parse_item_last_watched, reverse=True)
        watched.sort(key=self._parse_item_last_watched, reverse=True)

        loved_pool = loved[:3]
        watched_pool = watched[:3]
        # Tag each candidate with its origin bucket so the label can follow
        # the actual pick rather than re-checking flags after the fact.
        candidates: list[tuple[Any, bool]] = [(i, True) for i in loved_pool]
        candidates += [(i, False) for i in watched_pool]

        if not candidates:
            return

        seed, seed_is_loved = random.choice(candidates)
        label = "Because you loved" if seed_is_loved else "Because you watched"

        display_at_home = getattr(item_config, "display_at_home", True)
        catalogs.append(self.build_catalog_entry(seed, label, "watchly.item", display_at_home))
