from app.core.settings import UserSettings
from app.services.row_generator import RowGeneratorService
from app.services.scoring import ScoringService
from app.services.stremio_service import StremioService
from app.services.tmdb_service import TMDBService
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
        if item_id.startswith("tt") and config_id in ["watchly.loved", "watchly.watched"]:
            catalog_id = f"{config_id}.{item_id}"
        else:
            catalog_id = item_id

        name = item.get("name")
        # Truncate long names for cleaner UI
        if len(name) > 25:
            name = name[:25] + "..."

        return {
            "type": self.normalize_type(item.get("type")),
            "id": catalog_id,
            "name": f"{label} {name}",
            "extra": [],
        }

    async def get_dynamic_catalogs(
        self, library_items: list[dict], user_settings: UserSettings | None = None
    ) -> list[dict]:
        """
        Generate all dynamic catalog rows.
        """
        catalogs = []

        # 1. Build User Profile (same logic as recommendation service, but simplified)
        # Combine loved and watched
        all_items = library_items.get("loved", []) + library_items.get("watched", [])

        # Deduplicate
        unique_items = {item["_id"]: item for item in all_items}

        # Score items
        scored_objects = []

        # Use only recent history for freshness (Optimization shared with RecommendationService)
        sorted_history = sorted(unique_items.values(), key=lambda x: x.get("_mtime", ""), reverse=True)
        recent_history = sorted_history[:30]

        for item_data in recent_history:
            scored_obj = self.scoring_service.process_item(item_data)
            scored_objects.append(scored_obj)

        # 2. Generate Thematic Rows with Type-Specific Profiles
        # Generate for Movies (using only movie history)
        movie_profile = await self.user_profile_service.build_user_profile(scored_objects, content_type="movie")
        movie_rows = await self.row_generator.generate_rows(movie_profile, "movie")

        for row in movie_rows:
            catalogs.append({"type": "movie", "id": row.id, "name": row.title, "extra": []})

        # Generate for Series (using only series history)
        series_profile = await self.user_profile_service.build_user_profile(scored_objects, content_type="series")
        series_rows = await self.row_generator.generate_rows(series_profile, "series")

        for row in series_rows:
            catalogs.append({"type": "series", "id": row.id, "name": row.title, "extra": []})

        return catalogs

    async def get_watched_loved_catalogs(self, library_items: list[dict], user_settings: UserSettings | None = None):
        """Legacy compatibility wrapper - redirects to get_dynamic_catalogs"""
        return await self.get_dynamic_catalogs(library_items, user_settings)

    async def get_genre_based_catalogs(self, library_items: list[dict], user_settings: UserSettings | None = None):
        return []  # No longer needed separately
