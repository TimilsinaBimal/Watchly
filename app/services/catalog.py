import asyncio
import random
from datetime import datetime, timezone
from typing import Any

from loguru import logger

from app.core.constants import DISCOVER_ONLY_EXTRA
from app.core.settings import CatalogConfig, UserSettings
from app.services.interest_summary import interest_summary_service
from app.services.profile.integration import ProfileIntegration
from app.services.row_generator import RowGeneratorService
from app.services.scoring import ScoringService
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
        return order_map.get(get_config_id(catalog), 999)

    sorting_order = getattr(user_settings, "sorting_order", "default")

    if sorting_order == "movies_first":
        return sorted(
            catalogs,
            key=lambda x: (0 if x.get("type") == "movie" else 1, get_setting_index(x)),
        )

    if sorting_order == "series_first":
        return sorted(
            catalogs,
            key=lambda x: (0 if x.get("type") == "series" else 1, get_setting_index(x)),
        )

    return sorted(catalogs, key=get_setting_index)


class DynamicCatalogService:
    """
    Generates dynamic catalog rows based on user library and preferences.
    """

    def __init__(self, language: str = "en-US", tmdb_api_key: str | None = None):
        self.tmdb_service = get_tmdb_service(language=language, api_key=tmdb_api_key)
        self.scoring_service = ScoringService()
        self.profile_integration = ProfileIntegration(language=language, tmdb_api_key=tmdb_api_key)
        self.row_generator = RowGeneratorService(tmdb_service=self.tmdb_service)
        self.PROFILE_MAX_ITEMS = 50

    @staticmethod
    def normalize_type(type_):
        return "series" if type_ == "tv" else type_

    def build_catalog_entry(self, item, label, config_id, display_at_home: bool = True):
        item_id = item.get("_id", "")
        # Use watchly.{config_id}.{item_id} format for better organization
        if config_id in ["watchly.item", "watchly.loved", "watchly.watched"]:
            # New Item-based catalog format
            catalog_id = f"{config_id}.{item_id}"
        elif item_id.startswith("tt") and config_id in [
            "watchly.loved",
            "watchly.watched",
        ]:
            catalog_id = f"{config_id}.{item_id}"
        else:
            catalog_id = item_id

        name = item.get("name")

        extra = DISCOVER_ONLY_EXTRA if not display_at_home else []

        return {
            "type": self.normalize_type(item.get("type")),
            "id": catalog_id,
            "name": f"{label} {name}",
            "extra": extra,
        }

    def _get_smart_scored_items(self, library_items: dict, content_type: str, max_items: int = 50) -> list:
        """
        Get smart sampled items for profile building.
        Always includes all loved/liked/added items, then top watched items by interest_score.

        Args:
            library_items: Library items dict
            content_type: Type of content (movie/series)
            max_items: Maximum items to return (default: 50)

        Returns:
            List of ScoredItem objects
        """
        all_items = (
            library_items.get("loved", [])
            + library_items.get("liked", [])
            + library_items.get("watched", [])
            + library_items.get("added", [])
        )
        typed_items = [it for it in all_items if it.get("type") == content_type]

        if not typed_items:
            return []

        # Get added items (strong signal - user wants to watch these)
        added_item_ids = {it.get("_id") for it in library_items.get("added", [])}
        added_items = [it for it in typed_items if it.get("_id") in added_item_ids]

        # Separate loved/liked from watched items (excluding added)
        loved_liked_items = [
            it
            for it in typed_items
            if (it.get("_is_loved") or it.get("_is_liked")) and it.get("_id") not in added_item_ids
        ]
        watched_items = [
            it
            for it in typed_items
            if not (it.get("_is_loved") or it.get("_is_liked") or it.get("_id") in added_item_ids)
        ]

        # Always include all loved/liked/added items (score them)
        # These are strong signals of user intent
        strong_signal_items = loved_liked_items + added_items
        strong_signal_scored = [self.scoring_service.process_item(it) for it in strong_signal_items]

        # For watched items, score them and sort by interest_score
        watched_scored = [self.scoring_service.process_item(it) for it in watched_items]
        watched_scored.sort(key=lambda x: x.score, reverse=True)

        # Combine: all loved/liked/added + top watched items by score
        # Limit total to max_items
        remaining_slots = max(0, max_items - len(strong_signal_scored))
        top_watched = watched_scored[:remaining_slots]

        return strong_signal_scored + top_watched

    async def get_theme_based_catalogs(
        self,
        library_items: dict,
        user_settings: UserSettings | None = None,
        enabled_movie: bool = True,
        enabled_series: bool = True,
        display_at_home: bool = True,
        token: str | None = None,
    ) -> list[dict]:
        """Build thematic catalogs by profiling items using smart sampling."""
        # 1. Prepare Scored History using smart sampling (loved/liked + top watched by score)
        # We'll get items per content type in the generation function

        # 2. Extract Genre Filters
        excluded_movie_genres = []
        excluded_series_genres = []
        gemini_api_key = None
        if user_settings:
            excluded_movie_genres = [int(g) for g in user_settings.excluded_movie_genres]
            excluded_series_genres = [int(g) for g in user_settings.excluded_series_genres]
            gemini_api_key = user_settings.gemini_api_key

        logger.info(
            f"[Theme Catalogs] gemini_api_key={'SET' if gemini_api_key else 'NONE'},"
            f" token={'SET' if token else 'NONE'}"
        )

        # 3. Generate Rows
        async def _generate_for_type(media_type: str, genres: list[int]):
            logger.info(f"[Theme Catalogs] _generate_for_type called for {media_type}")

            # Build profile using new system
            profile, _, _ = await self.profile_integration.build_profile_from_library(
                library_items, media_type, None, None
            )
            if not profile:
                logger.warning(f"Failed to build profile for {media_type}")
                return media_type, []

            # Generate interest summary if API key is present.
            if gemini_api_key and token:
                try:
                    logger.info(f"Generating interest summary for {media_type}...")
                    summary = await interest_summary_service.generate_summary(profile, gemini_api_key)
                    if summary:
                        profile.interest_summary = summary
                        logger.info(f"Interest summary generated for {media_type}: {summary[:80]}...")
                    else:
                        logger.warning(f"Interest summary generation returned empty for {media_type}")
                except Exception as e:
                    logger.warning(f"Failed to generate interest summary for {media_type}: {e}")
            else:
                logger.info(
                    f"[Theme Catalogs] Skipping summary: gemini_api_key={'SET' if gemini_api_key else 'NONE'},"
                    f" token={'SET' if token else 'NONE'}"
                )

            # Always save the updated profile (with or without summary)
            if token:
                try:
                    await user_cache.set_profile(token, media_type, profile)
                    logger.info(f"Saved profile for {media_type} (has_summary={profile.interest_summary is not None})")
                except Exception as e:
                    logger.warning(f"Failed to save profile for {media_type}: {e}")

            try:
                catalogs = await self.row_generator.generate_rows(profile, media_type, api_key=gemini_api_key)
                return media_type, catalogs
            except Exception as e:
                logger.error(f"Failed to generate thematic rows for {media_type}: {e}")
                raise e

        tasks = []
        if enabled_movie:
            tasks.append(_generate_for_type("movie", excluded_movie_genres))
        if enabled_series:
            tasks.append(_generate_for_type("series", excluded_series_genres))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 4. Assembly with error handling
        catalogs = []

        extra = DISCOVER_ONLY_EXTRA if not display_at_home else []

        for result in results:
            if isinstance(result, Exception):
                continue
            media_type, rows = result
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

    async def get_dynamic_catalogs(
        self,
        library_items: dict,
        user_settings: UserSettings | None = None,
        token: str | None = None,
    ) -> list[dict]:
        """Generate all dynamic catalog rows based on enabled configurations."""
        catalogs = []
        if not user_settings:
            return catalogs

        # 1. Resolve Configs
        theme_cfg, loved_cfg, watched_cfg = self._resolve_catalog_configs(user_settings)

        # 2. Add Thematic Catalogs
        if theme_cfg and theme_cfg.enabled:
            # Filter theme catalogs by enabled_movie/enabled_series
            enabled_movie = getattr(theme_cfg, "enabled_movie", True)
            enabled_series = getattr(theme_cfg, "enabled_series", True)
            display_at_home = getattr(theme_cfg, "display_at_home", True)
            theme_catalogs = await self.get_theme_based_catalogs(
                library_items,
                user_settings,
                enabled_movie,
                enabled_series,
                display_at_home,
                token,
            )
            catalogs.extend(theme_catalogs)

        # 3. Add Item-Based Catalogs (Movies & Series)
        for mtype in ["movie", "series"]:
            await self._add_item_based_rows(catalogs, library_items, mtype, loved_cfg, watched_cfg)

        # 4. Add watchly.rec catalog
        catalogs.extend(get_catalogs_from_config(user_settings, "watchly.rec", "Top Picks for You", True, True))

        # 5. Add watchly.creators catalog
        catalogs.extend(
            get_catalogs_from_config(
                user_settings,
                "watchly.creators",
                "From your favourite Creators",
                False,
                False,
            )
        )

        # 6. Add watchly.all.loved catalog
        catalogs.extend(
            get_catalogs_from_config(
                user_settings,
                "watchly.all.loved",
                "Based on what you loved",
                True,
                True,
            )
        )

        # 7. Add watchly.liked.all catalog
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

    def _resolve_catalog_configs(self, user_settings: UserSettings) -> tuple[Any, Any, Any]:
        """Extract and fallback catalog configurations from user settings."""
        cfg_map = {c.id: c for c in user_settings.catalogs}

        theme = cfg_map.get("watchly.theme")
        loved = cfg_map.get("watchly.loved")
        watched = cfg_map.get("watchly.watched")

        # Fallback for old settings format (watchly.item)
        if not loved and not watched:
            old_item = cfg_map.get("watchly.item")
            if old_item and old_item.enabled:
                loved = CatalogConfig(id="watchly.loved", name=None, enabled=True)
                watched = CatalogConfig(id="watchly.watched", name=None, enabled=True)

        return theme, loved, watched

    def _parse_item_last_watched(self, item: dict) -> datetime:
        """Helper to extract and parse the most relevant activity date for an item."""
        val = item.get("state", {}).get("lastWatched")
        if val:
            try:
                if isinstance(val, str):
                    return datetime.fromisoformat(val.replace("Z", "+00:00"))
                return val
            except (ValueError, TypeError):
                pass

        # Fallback to mtime
        val = item.get("_mtime")
        if val:
            try:
                return datetime.fromisoformat(str(val).replace("Z", "+00:00"))
            except (ValueError, TypeError):
                pass
        return datetime.min.replace(tzinfo=timezone.utc)

    async def _add_item_based_rows(
        self,
        catalogs: list,
        library_items: dict,
        content_type: str,
        loved_config,
        watched_config,
    ):
        # Check if this content type is enabled for the configs
        def is_type_enabled(config, content_type: str) -> bool:
            if not config:
                return False
            if content_type == "movie":
                return getattr(config, "enabled_movie", True)
            elif content_type == "series":
                return getattr(config, "enabled_series", True)
            return True

        # 1. More Like <Loved Item>
        last_loved = None  # Initialize for the watched check
        if loved_config and loved_config.enabled and is_type_enabled(loved_config, content_type):
            loved = [i for i in library_items.get("loved", []) if i.get("type") == content_type]
            loved.sort(key=self._parse_item_last_watched, reverse=True)

            # gather random last loved from last 3 items
            last_loved = random.choice(loved[:3]) if loved else None
            if last_loved:
                label = loved_config.name if loved_config.name else "More like"
                loved_config_display_at_home = getattr(loved_config, "display_at_home", True)
                catalogs.append(
                    self.build_catalog_entry(last_loved, label, "watchly.loved", loved_config_display_at_home)
                )

        # 2. Because you watched <Watched Item>
        if watched_config and watched_config.enabled and is_type_enabled(watched_config, content_type):
            watched = [i for i in library_items.get("watched", []) if i.get("type") == content_type]
            watched.sort(key=self._parse_item_last_watched, reverse=True)

            # watched cannot be similar to loved
            if last_loved:
                watched = [i for i in watched if i.get("_id") != last_loved.get("_id")]

            # gather random last watched from last 3 items
            last_watched = random.choice(watched[:3]) if watched else None

            if last_watched:
                label = watched_config.name if watched_config.name else "Because you watched"
                watched_config_display_at_home = getattr(watched_config, "display_at_home", True)
                catalogs.append(
                    self.build_catalog_entry(
                        last_watched,
                        label,
                        "watchly.watched",
                        watched_config_display_at_home,
                    )
                )
