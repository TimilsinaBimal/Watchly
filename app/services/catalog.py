from app.core.settings import UserSettings
from app.services.row_generator import RowGeneratorService
from app.services.scoring import ScoringService
from app.services.stremio_service import StremioService
from app.services.tmdb_service import TMDBService
from app.services.translation import translation_service
from app.services.user_profile import UserProfileService


class DynamicCatalogService:
    """
    Generates dynamic catalog rows based on user library and preferences.
    """

    def __init__(self, stremio_service: StremioService):
        self.stremio_service = stremio_service
        self.tmdb_service = TMDBService()
        self.scoring_service = ScoringService()
        self.user_profile_service = UserProfileService()
        self.row_generator = RowGeneratorService(tmdb_service=self.tmdb_service)

    @staticmethod
    def normalize_type(type_):
        return "series" if type_ == "tv" else type_

    def build_catalog_entry(self, item, label, config_id):
        item_id = item.get("_id", "")
        # Use watchly.{config_id}.{item_id} format for better organization
        if config_id == "watchly.item":
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
        self, library_items: list[dict], user_settings: UserSettings | None = None
    ) -> list[dict]:
        catalogs = []
        lang = user_settings.language if user_settings else "en-US"

        # 1. Build User Profile
        # Combine loved and watched
        all_items = library_items.get("loved", []) + library_items.get("watched", [])

        # Deduplicate
        unique_items = {item["_id"]: item for item in all_items}

        # Score items
        scored_objects = []

        # Use only recent history for freshness
        sorted_history = sorted(unique_items.values(), key=lambda x: x.get("_mtime", ""), reverse=True)
        recent_history = sorted_history[:30]

        for item_data in recent_history:
            scored_obj = self.scoring_service.process_item(item_data)
            scored_objects.append(scored_obj)

        # Get excluded genres
        excluded_movie_genres = []
        excluded_series_genres = []
        if user_settings:
            excluded_movie_genres = [int(g) for g in user_settings.excluded_movie_genres]
            excluded_series_genres = [int(g) for g in user_settings.excluded_series_genres]

        # 2. Generate Thematic Rows with Type-Specific Profiles
        # Generate for Movies
        movie_profile = await self.user_profile_service.build_user_profile(
            scored_objects, content_type="movie", excluded_genres=excluded_movie_genres
        )
        movie_rows = await self.row_generator.generate_rows(movie_profile, "movie")

        for row in movie_rows:
            translated_title = await translation_service.translate(row.title, lang)
            catalogs.append({"type": "movie", "id": row.id, "name": translated_title, "extra": []})

        # Generate for Series
        series_profile = await self.user_profile_service.build_user_profile(
            scored_objects, content_type="series", excluded_genres=excluded_series_genres
        )
        series_rows = await self.row_generator.generate_rows(series_profile, "series")

        for row in series_rows:
            translated_title = await translation_service.translate(row.title, lang)
            catalogs.append({"type": "series", "id": row.id, "name": translated_title, "extra": []})

        return catalogs

    async def get_dynamic_catalogs(
        self, library_items: list[dict], user_settings: UserSettings | None = None
    ) -> list[dict]:
        """
        Generate all dynamic catalog rows.
        """
        lang = user_settings.language if user_settings else "en-US"

        include_item_based_rows = bool(
            next((c for c in user_settings.catalogs if c.id == "watchly.item" and c.enabled), True)
        )
        include_theme_based_rows = bool(
            next((c for c in user_settings.catalogs if c.id == "watchly.theme" and c.enabled), True)
        )
        catalogs = []

        if include_theme_based_rows:
            catalogs.extend(await self.get_theme_based_catalogs(library_items, user_settings))

        # 3. Add Item-Based Rows
        if include_item_based_rows:
            # For Movies
            await self._add_item_based_rows(catalogs, library_items, "movie", lang)
            # For Series
            await self._add_item_based_rows(catalogs, library_items, "series", lang)

        return catalogs

    async def _add_item_based_rows(self, catalogs: list, library_items: dict, content_type: str, language: str):
        """Helper to add 'Because you watched' and 'More like' rows."""

        # Translate labels
        label_more_like = await translation_service.translate("More like", language)
        label_bc_watched = await translation_service.translate("Because you watched", language)

        # Helper to parse date
        def get_date(item):
            import datetime

            val = item.get("state", {}).get("lastWatched")
            if val:
                try:
                    if isinstance(val, str):
                        return datetime.datetime.fromisoformat(val.replace("Z", "+00:00"))
                    return val
                except (ValueError, TypeError):
                    pass
            # Fallback to mtime
            val = item.get("_mtime")
            if val:
                try:
                    return datetime.datetime.fromisoformat(str(val).replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    pass
            return datetime.datetime.min.replace(tzinfo=datetime.UTC)

        # 1. More Like <Loved Item>
        loved = [i for i in library_items.get("loved", []) if i.get("type") == content_type]
        loved.sort(key=get_date, reverse=True)

        last_loved = loved[0] if loved else None
        if last_loved:
            catalogs.append(self.build_catalog_entry(last_loved, label_more_like, "watchly.item"))

        # 2. Because you watched <Watched Item>
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
            catalogs.append(self.build_catalog_entry(last_watched, label_bc_watched, "watchly.item"))
