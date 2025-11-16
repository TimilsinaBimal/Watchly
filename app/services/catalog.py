from app.services.stremio_service import StremioService
from app.services.tmdb_service import TMDBService

import asyncio
from .tmdb.genre import MOVIE_GENRE_TO_ID_MAP, SERIES_GENRE_TO_ID_MAP
from collections import Counter


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
        movie_tasks = [self.tmdb_service.get_addon_meta("movie", {item.get('_id')}) for item in loved_movies]
        series_tasks = [self.tmdb_service.get_addon_meta("series", {item.get('_id')}) for item in loved_series]
        movie_details = await asyncio.gather(*movie_tasks)
        series_details = await asyncio.gather(*series_tasks)

        # now fetch all genres for moviees and series and sort them by their occurance
        movie_genres = [detail.get("genres", []) for detail in movie_details]
        series_genres = [detail.get("genres", []) for detail in series_details]

        # now flatten list and count the occurance of each genre for both movies and series separately
        movie_genre_counts = Counter([genre for sublist in movie_genres for genre in sublist])
        series_genre_counts = Counter([genre for sublist in series_genres for genre in sublist])
        sorted_movie_genres = sorted(movie_genre_counts.items(), key=lambda x: x[1], reverse=True)
        sorted_series_genres = sorted(series_genre_counts.items(), key=lambda x: x[1], reverse=True)

        # now get the top 5 genres for movies and series
        top_5_movie_genres = sorted_movie_genres[:5]
        top_5_series_genres = sorted_series_genres[:5]

        # convert id to name
        top_5_movie_genres_names = [MOVIE_GENRE_TO_ID_MAP[genre_id] for genre_id, _ in top_5_movie_genres]
        top_5_series_genres_names = [SERIES_GENRE_TO_ID_MAP[genre_id] for genre_id, _ in top_5_series_genres]

        # prepare name for combined genre for first two and then last three
        catalogs1 = {
            "type": "movie",
            "id": f"watchly.genre.{top_5_movie_genres[0]}-{top_5_movie_genres[1]}",
            "name": f"{top_5_movie_genres_names[0]}-{top_5_movie_genres_names[1]}",
            "extra": [],
        }
        catalogs2 = {
            "type": "movie",
            "id": f"watchly.genre.{top_5_movie_genres[2]}_{top_5_movie_genres[3]}_{top_5_movie_genres[4]}",
            "name": (
                f"{top_5_movie_genres_names[2]}-{top_5_movie_genres_names[3]}-{top_5_movie_genres_names[4]}"
            ),
            "extra": [],
        }
        catalogs3 = {
            "type": "series",
            "id": f"watchly.genre.{top_5_series_genres[0]}-{top_5_series_genres[1]}",
            "name": f"{top_5_series_genres_names[0]}-{top_5_series_genres_names[1]}",
            "extra": [],
        }
        catalogs4 = {
            "type": "series",
            "id": f"watchly.genre.{top_5_series_genres[2]}_{top_5_series_genres[3]}_{top_5_series_genres[4]}",
            "name": (
                f"{top_5_series_genres_names[2]}-{top_5_series_genres_names[3]}-{top_5_series_genres_names[4]}"
            ),
            "extra": [],
        }
        return [catalogs1, catalogs2, catalogs3, catalogs4]
