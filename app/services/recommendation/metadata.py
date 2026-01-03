import asyncio
from typing import Any

from loguru import logger

from app.core.constants import DEFAULT_CONCURRENCY_LIMIT
from app.services.poster_ratings.factory import PosterProvider, poster_ratings_factory


class RecommendationMetadata:
    """
    Handles fetching and formatting metadata for Stremio.
    """

    @staticmethod
    def extract_year(item: dict[str, Any]) -> int | None:
        """Extract year from TMDB item."""
        date_str = item.get("release_date") or item.get("first_air_date")
        if not date_str:
            ri = item.get("releaseInfo")
            if isinstance(ri, str) and len(ri) >= 4 and ri[:4].isdigit():
                return int(ri[:4])
            return None
        try:
            return int(date_str[:4])
        except Exception:
            return None

    @classmethod
    async def format_for_stremio(
        cls, details: dict[str, Any], media_type: str, user_settings: Any = None
    ) -> dict[str, Any] | None:
        """Format TMDB details into Stremio metadata object."""
        external_ids = details.get("external_ids", {})
        imdb_id = external_ids.get("imdb_id")
        tmdb_id_raw = details.get("id")

        if imdb_id:
            stremio_id = imdb_id
        elif tmdb_id_raw:
            stremio_id = f"tmdb:{tmdb_id_raw}"
        else:
            return None

        title = details.get("title") or details.get("name")
        if not title:
            return None

        # Base Fields
        genres_full = details.get("genres", []) or []
        release_date = details.get("release_date") or details.get("first_air_date") or ""

        meta_data = {
            "id": stremio_id,
            "imdb_id": imdb_id,
            "type": "series" if media_type in ["tv", "series"] else "movie",
            "name": title,
            "poster": cls._get_poster_url(details, stremio_id, user_settings),
            "background": cls._get_backdrop_url(details),
            "description": details.get("overview"),
            "releaseInfo": release_date[:4] if release_date else None,
            "imdbRating": str(details.get("vote_average", "")),
            "genres": [g.get("name") for g in genres_full if isinstance(g, dict)],
            "vote_average": details.get("vote_average"),
            "vote_count": details.get("vote_count"),
            "popularity": details.get("popularity"),
            "original_language": details.get("original_language"),
            "_external_ids": external_ids,
            "_tmdb_id": tmdb_id_raw,
            "genre_ids": [g.get("id") for g in genres_full if isinstance(g, dict) and g.get("id") is not None],
        }

        # Extensions
        runtime_str = cls._extract_runtime_string(details)
        if runtime_str:
            meta_data["runtime"] = runtime_str

        if media_type == "movie":
            coll = details.get("belongs_to_collection")
            if isinstance(coll, dict):
                meta_data["_collection_id"] = coll.get("id")

        # Cast & Crew
        cast = details.get("credits", {}).get("cast", []) or []
        meta_data["_top_cast_ids"] = [c.get("id") for c in cast[:3] if isinstance(c, dict) and c.get("id")]

        # Keywords & Credits for similarity re-ranking
        if details.get("keywords"):
            meta_data["keywords"] = details.get("keywords")
        if details.get("credits"):
            meta_data["credits"] = details.get("credits")

        return meta_data

    @staticmethod
    def _get_poster_url(details: dict, item_id: str, user_settings: Any) -> str | None:
        """Resolve poster URL using poster rating provider if configured, otherwise TMDB."""
        path = details.get("poster_path")
        poster_url = f"https://image.tmdb.org/t/p/w500{path}"

        if user_settings:
            poster_rating = user_settings.poster_rating
            if poster_rating and poster_rating.api_key:
                try:
                    provider_enum = PosterProvider(poster_rating.provider)
                    poster_url = poster_ratings_factory.get_poster_url(
                        provider_enum, poster_rating.api_key, "imdb", item_id, fallback=poster_url
                    )
                except ValueError as e:
                    logger.warning(f"Error getting poster URL for item ID {item_id}: {e}")
                    pass

        return poster_url

    @staticmethod
    def _get_backdrop_url(details: dict) -> str | None:
        """Construct full TMDB backdrop URL."""
        path = details.get("backdrop_path")
        return f"https://image.tmdb.org/t/p/original{path}" if path else None

    @staticmethod
    def _extract_runtime_string(details: dict) -> str | None:
        """Extract and format runtime from either movie or TV format."""
        runtime = details.get("runtime")
        if not runtime and details.get("episode_run_time"):
            runtime = details.get("episode_run_time")[0]
        return f"{runtime} min" if runtime else None

    @classmethod
    async def fetch_batch(
        cls,
        tmdb_service: Any,
        items: list[dict[str, Any]],
        media_type: str,
        user_settings: Any = None,
    ) -> list[dict[str, Any]]:
        """Fetch details for a batch of items in parallel with target-based short-circuiting."""
        final_results = []
        valid_items = [it for it in items if it.get("id")]
        query_type = "movie" if media_type == "movie" else "tv"
        sem = asyncio.Semaphore(DEFAULT_CONCURRENCY_LIMIT)

        async def _fetch_one(tid: int):
            async with sem:
                try:
                    if query_type == "movie":
                        return await tmdb_service.get_movie_details(tid)
                    return await tmdb_service.get_tv_details(tid)
                except Exception:
                    return None

        tasks = [_fetch_one(it.get("id")) for it in valid_items]
        details_list = await asyncio.gather(*tasks)

        format_task = [
            cls.format_for_stremio(details, media_type, user_settings) for details in details_list if details
        ]

        formatted_list = await asyncio.gather(*format_task, return_exceptions=True)

        for formatted in formatted_list:
            if isinstance(formatted, Exception):
                logger.warning(f"Error formatting metadata: {formatted}")
                continue
            if formatted:
                final_results.append(formatted)

        return final_results
