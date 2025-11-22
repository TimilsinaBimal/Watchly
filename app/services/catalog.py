import asyncio
from collections import Counter

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

    def build_catalog_entry(self, item, label):
        return {
            "type": self.normalize_type(item.get("type")),
            "id": item.get("_id"),
            "name": f"Because you {label} {item.get('name')}",
            "extra": [],
        }

    def process_items(self, items, seen_items, seed, label):
        entries = []
        for item in items:
            type_ = self.normalize_type(item.get("type"))
            if item.get("_id") in seen_items or seed[type_]:
                continue
            seen_items.add(item.get("_id"))
            seed[type_] = True
            entries.append(self.build_catalog_entry(item, label))
        return entries

    async def get_watched_loved_catalogs(self, library_items: list[dict]):
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

        catalogs += self.process_items(loved_items, seen_items, seed["loved"], "Loved")
        catalogs += self.process_items(watched_items, seen_items, seed["watched"], "Watched")

        return catalogs

    async def get_genre_based_catalogs(self, library_items: list[dict]):
        # get separate movies and series lists from loved items
        loved_movies = [item for item in library_items.get("loved", []) if item.get("type") == "movie"]
        loved_series = [item for item in library_items.get("loved", []) if item.get("type") == "series"]

        # only take last 5 results from loved movies and series
        loved_movies = loved_movies[:5]
        loved_series = loved_series[:5]

        # fetch details:: genre details from tmdb addon
        movie_tasks = [self.tmdb_service.get_addon_meta("movie", item.get("_id").strip()) for item in loved_movies]
        series_tasks = [self.tmdb_service.get_addon_meta("series", item.get("_id").strip()) for item in loved_series]
        movie_details = await asyncio.gather(*movie_tasks)
        series_details = await asyncio.gather(*series_tasks)

        # now fetch all genres for moviees and series and sort them by their occurance
        movie_genres = [detail.get("meta", {}).get("genres", []) for detail in movie_details]
        series_genres = [detail.get("meta", {}).get("genres", []) for detail in series_details]

        # now flatten list and count the occurance of each genre for both movies and series separately
        movie_genre_counts = Counter(
            [genre for sublist in movie_genres for genre in sublist if genre in MOVIE_GENRE_TO_ID_MAP]
        )
        series_genre_counts = Counter(
            [genre for sublist in series_genres for genre in sublist if genre in SERIES_GENRE_TO_ID_MAP]
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

        catalogs.append(
            {
                "type": "movie",
                "id": f"watchly.genre.{'_'.join(top_2_movie_genres)}",
                "name": "You might also Like",
                "extra": [],
            }
        )

        catalogs.append(
            {
                "type": "series",
                "id": f"watchly.genre.{'_'.join(top_2_series_genres)}",
                "name": "You might also Like",
                "extra": [],
            }
        )

        return catalogs
