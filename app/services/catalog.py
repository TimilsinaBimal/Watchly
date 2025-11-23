import asyncio
from collections import Counter

from loguru import logger

from app.core.settings import UserSettings
from app.services.stremio_service import StremioService
from app.services.tmdb_service import TMDBService

from .tmdb.genre import MOVIE_GENRE_TO_ID_MAP, SERIES_GENRE_TO_ID_MAP


class DynamicCatalogService:

    def __init__(self, stremio_service: StremioService):
        self.stremio_service = stremio_service
        self.tmdb_service = TMDBService()

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
        return {
            "type": self.normalize_type(item.get("type")),
            "id": catalog_id,
            "name": f"{label} {item.get('name')}",
            "extra": [],
        }

    def process_items(self, items, seen_items, seed, label, config_id):
        entries = []
        for item in items:
            type_ = self.normalize_type(item.get("type"))
            if item.get("_id") in seen_items or seed[type_]:
                continue
            seen_items.add(item.get("_id"))
            seed[type_] = True
            entries.append(self.build_catalog_entry(item, label, config_id))
        return entries

    async def get_watched_loved_catalogs(self, library_items: list[dict], user_settings: UserSettings | None = None):
        seen_items = set()
        catalogs = []

        seed = {
            "watched": {
                "movie": False,
                "series": False,
            },
            "loved": {
                "movie": False,
                "series": False,
            },
        }

        loved_items = library_items.get("loved", [])
        watched_items = library_items.get("watched", [])

        # Determine labels and enablement from settings
        loved_label = "Because you Loved"
        watched_label = "Because you Watched"
        loved_enabled = True
        watched_enabled = True

        if user_settings:
            loved_config = next((c for c in user_settings.catalogs if c.id == "watchly.loved"), None)
            watched_config = next((c for c in user_settings.catalogs if c.id == "watchly.watched"), None)

            if loved_config:
                loved_enabled = loved_config.enabled
                if loved_config.name:
                    loved_label = loved_config.name

            if watched_config:
                watched_enabled = watched_config.enabled
                if watched_config.name:
                    watched_label = watched_config.name

        if loved_enabled:
            catalogs += self.process_items(loved_items, seen_items, seed["loved"], loved_label, "watchly.loved")

        if watched_enabled:
            catalogs += self.process_items(
                watched_items, seen_items, seed["watched"], watched_label, "watchly.watched"
            )

        return catalogs

    async def _get_item_genres(self, item_id: str, item_type: str) -> list[str]:
        """Fetch genres for a specific item from TMDB."""
        try:
            # Convert IMDB ID to TMDB ID
            tmdb_id = None
            media_type = "movie" if item_type == "movie" else "tv"

            if item_id.startswith("tt"):
                tmdb_id, _ = await self.tmdb_service.find_by_imdb_id(item_id)
            elif item_id.startswith("tmdb:"):
                tmdb_id = int(item_id.split(":")[1])

            if not tmdb_id:
                return []

            # Fetch details
            if media_type == "movie":
                details = await self.tmdb_service.get_movie_details(tmdb_id)
            else:
                details = await self.tmdb_service.get_tv_details(tmdb_id)

            return [g.get("name") for g in details.get("genres", [])]
        except Exception as e:
            logger.warning(f"Failed to fetch genres for {item_id}: {e}")
            return []

    async def get_genre_based_catalogs(self, library_items: list[dict], user_settings: UserSettings | None = None):
        genre_label = "You might also Like"
        genre_enabled = True

        if user_settings:
            genre_config = next((c for c in user_settings.catalogs if c.id == "watchly.genre"), None)
            if genre_config:
                genre_enabled = genre_config.enabled
                if genre_config.name:
                    genre_label = genre_config.name

        if not genre_enabled:
            return []

        # get separate movies and series lists from loved items
        loved_movies = [item for item in library_items.get("loved", []) if item.get("type") == "movie"]
        loved_series = [item for item in library_items.get("loved", []) if item.get("type") == "series"]

        # only take last 5 results from loved movies and series
        loved_movies = loved_movies[:5]
        loved_series = loved_series[:5]

        # fetch genres concurrently
        movie_tasks = [self._get_item_genres(item.get("_id").strip(), "movie") for item in loved_movies]
        series_tasks = [self._get_item_genres(item.get("_id").strip(), "series") for item in loved_series]

        movie_genres_list = await asyncio.gather(*movie_tasks)
        series_genres_list = await asyncio.gather(*series_tasks)

        # now flatten list and count the occurance of each genre for both movies and series separately
        movie_genre_counts = Counter(
            [genre for sublist in movie_genres_list for genre in sublist if genre in MOVIE_GENRE_TO_ID_MAP]
        )
        series_genre_counts = Counter(
            [genre for sublist in series_genres_list for genre in sublist if genre in SERIES_GENRE_TO_ID_MAP]
        )
        sorted_movie_genres = sorted(movie_genre_counts.items(), key=lambda x: x[1], reverse=True)
        sorted_series_genres = sorted(series_genre_counts.items(), key=lambda x: x[1], reverse=True)

        # now get the top 2 genres for movies and series
        top_2_movie_genre_names = [genre for genre, _ in sorted_movie_genres[:2]]
        top_2_series_genre_names = [genre for genre, _ in sorted_series_genres[:2]]

        # convert id to name
        top_2_movie_genres = [str(MOVIE_GENRE_TO_ID_MAP[genre_name]) for genre_name in top_2_movie_genre_names]
        top_2_series_genres = [str(SERIES_GENRE_TO_ID_MAP[genre_name]) for genre_name in top_2_series_genre_names]
        catalogs = []

        if top_2_movie_genres:
            catalogs.append(
                {
                    "type": "movie",
                    "id": f"watchly.genre.{'_'.join(top_2_movie_genres)}",
                    "name": genre_label,
                    "extra": [],
                }
            )

        if top_2_series_genres:
            catalogs.append(
                {
                    "type": "series",
                    "id": f"watchly.genre.{'_'.join(top_2_series_genres)}",
                    "name": genre_label,
                    "extra": [],
                }
            )

        return catalogs
