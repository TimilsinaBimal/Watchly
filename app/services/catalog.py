import asyncio
from datetime import datetime, timezone

from app.core.settings import CatalogConfig, UserSettings
from app.services.profile.service import UserProfileService
from app.services.row_generator import RowGeneratorService
from app.services.scoring import ScoringService
from app.services.tmdb.service import get_tmdb_service


class DynamicCatalogService:
    """
    Generates dynamic catalog rows based on user library and preferences.
    """

    def __init__(self, language: str = "en-US"):
        self.tmdb_service = get_tmdb_service(language=language)
        self.scoring_service = ScoringService()
        self.user_profile_service = UserProfileService(language=language)
        self.row_generator = RowGeneratorService(tmdb_service=self.tmdb_service)
        self.HISTORY_LIMIT = 30

    @staticmethod
    def normalize_type(type_):
        return "series" if type_ == "tv" else type_

    def build_catalog_entry(self, item, label, config_id):
        item_id = item.get("_id", "")
        # Use watchly.{config_id}.{item_id} format for better organization
        if config_id in ["watchly.item", "watchly.loved", "watchly.watched"]:
            # New Item-based catalog format
            catalog_id = f"{config_id}.{item_id}"
        elif item_id.startswith("tt") and config_id in ["watchly.loved", "watchly.watched"]:
            catalog_id = f"{config_id}.{item_id}"
        else:
            catalog_id = item_id

        name = item.get("name")

        return {
            "type": self.normalize_type(item.get("type")),
            "id": catalog_id,
            "name": f"{label} {name}",
            "extra": [],
        }

    async def get_theme_based_catalogs(
        self, library_items: dict, user_settings: UserSettings | None = None
    ) -> list[dict]:
        catalogs = []

        # 1. Build User Profile
        # Combine loved and watched
        all_items = library_items.get("loved", []) + library_items.get("watched", [])

        # Deduplicate
        unique_items = {item["_id"]: item for item in all_items}

        # Score items
        scored_objects = []

        # Use only recent history for freshness
        sorted_history = sorted(
            unique_items.values(), key=lambda x: x.get("state", {}).get("lastWatched", "") or "", reverse=True
        )
        recent_history = sorted_history[: self.HISTORY_LIMIT]

        for item_data in recent_history:
            scored_obj = self.scoring_service.process_item(item_data)
            scored_objects.append(scored_obj)

        # Get excluded genres
        excluded_movie_genres = []
        excluded_series_genres = []
        if user_settings:
            excluded_movie_genres = [int(g) for g in user_settings.excluded_movie_genres]
            excluded_series_genres = [int(g) for g in user_settings.excluded_series_genres]

        # 2. Generate Thematic Rows in Parallel
        async def process_media(media_type, genres):
            profile = await self.user_profile_service.build_user_profile(
                scored_objects, content_type=media_type, excluded_genres=genres
            )
            return await self.row_generator.generate_rows(profile, media_type)

        results = await asyncio.gather(
            process_media("movie", excluded_movie_genres),
            process_media("series", excluded_series_genres),
            return_exceptions=True,
        )

        movie_rows = results[0] if not isinstance(results[0], Exception) else []
        series_rows = results[1] if not isinstance(results[1], Exception) else []

        for row in movie_rows:
            catalogs.append({"type": "movie", "id": row.id, "name": row.title, "extra": []})

        for row in series_rows:
            catalogs.append({"type": "series", "id": row.id, "name": row.title, "extra": []})

        return catalogs

    async def get_dynamic_catalogs(self, library_items: dict, user_settings: UserSettings | None = None) -> list[dict]:
        """
        Generate all dynamic catalog rows.
        """
        catalogs = []
        lang = user_settings.language if user_settings else "en-US"

        # Theme Based
        theme_config = next((c for c in user_settings.catalogs if c.id == "watchly.theme"), None)

        if theme_config and theme_config.enabled:
            catalogs.extend(await self.get_theme_based_catalogs(library_items, user_settings))

        # Item Based (Loved/Watched)
        loved_config = next((c for c in user_settings.catalogs if c.id == "watchly.loved"), None)
        watched_config = next((c for c in user_settings.catalogs if c.id == "watchly.watched"), None)

        # Fallback for old settings (watchly.item)
        if not loved_config and not watched_config:
            old_config = next((c for c in user_settings.catalogs if c.id == "watchly.item"), None)
            if old_config and old_config.enabled:
                # Create temporary configs
                loved_config = CatalogConfig(id="watchly.loved", name=None, enabled=True)
                watched_config = CatalogConfig(id="watchly.watched", name=None, enabled=True)

        # Movies
        await self._add_item_based_rows(catalogs, library_items, "movie", lang, loved_config, watched_config)
        # Series
        await self._add_item_based_rows(catalogs, library_items, "series", lang, loved_config, watched_config)

        return catalogs

    async def _add_item_based_rows(
        self,
        catalogs: list,
        library_items: dict,
        content_type: str,
        language: str,
        loved_config,
        watched_config,
    ):
        """Helper to add 'Because you watched' and 'More like' rows."""

        # Helper to parse date
        def get_date(item):
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

        # 1. More Like <Loved Item>
        last_loved = None  # Initialize for the watched check
        if loved_config and loved_config.enabled:
            loved = [i for i in library_items.get("loved", []) if i.get("type") == content_type]
            loved.sort(key=get_date, reverse=True)

            last_loved = loved[0] if loved else None
            if last_loved:
                label = loved_config.name if loved_config.name else "More like"
                catalogs.append(self.build_catalog_entry(last_loved, label, "watchly.loved"))

        # 2. Because you watched <Watched Item>
        if watched_config and watched_config.enabled:
            watched = [i for i in library_items.get("watched", []) if i.get("type") == content_type]
            watched.sort(key=get_date, reverse=True)

            last_watched = None
            for item in watched:
                # Avoid duplicate row if it's the same item as 'More like'
                if last_loved and item.get("_id") == last_loved.get("_id"):
                    continue
                last_watched = item
                break

            if last_watched:
                label = watched_config.name if watched_config.name else "Because you watched"
                catalogs.append(self.build_catalog_entry(last_watched, label, "watchly.watched"))
