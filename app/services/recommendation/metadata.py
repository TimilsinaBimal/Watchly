import asyncio
from typing import Any

from app.services.rpdb import RPDBService


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

    @staticmethod
    async def format_for_stremio(
        details: dict[str, Any], media_type: str, user_settings: Any = None
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

        poster_path = details.get("poster_path")
        backdrop_path = details.get("backdrop_path")
        release_date = details.get("release_date") or details.get("first_air_date") or ""
        year = release_date[:4] if release_date else None

        if user_settings and user_settings.rpdb_key:
            poster_url = RPDBService.get_poster_url(user_settings.rpdb_key, stremio_id)
        else:
            poster_url = f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else None

        genres_full = details.get("genres", []) or []
        genre_ids = [g.get("id") for g in genres_full if isinstance(g, dict) and g.get("id") is not None]

        meta_data = {
            "id": stremio_id,
            "imdb_id": imdb_id,
            "type": "series" if media_type in ["tv", "series"] else "movie",
            "name": title,
            "poster": poster_url,
            "background": f"https://image.tmdb.org/t/p/original{backdrop_path}" if backdrop_path else None,
            "description": details.get("overview"),
            "releaseInfo": year,
            "imdbRating": str(details.get("vote_average", "")),
            "genres": [g.get("name") for g in genres_full],
            "vote_average": details.get("vote_average"),
            "vote_count": details.get("vote_count"),
            "popularity": details.get("popularity"),
            "original_language": details.get("original_language"),
            "_external_ids": external_ids,
            "_tmdb_id": details.get("id"),
            "genre_ids": genre_ids,
        }

        # Add runtime
        runtime = details.get("runtime")
        if not runtime and details.get("episode_run_time"):
            runtime = details.get("episode_run_time")[0]
        if runtime:
            meta_data["runtime"] = f"{runtime} min"

        # Movies only: collections
        if media_type == "movie":
            coll = details.get("belongs_to_collection") or {}
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

    @classmethod
    async def fetch_batch(
        cls,
        tmdb_service: Any,
        items: list[dict[str, Any]],
        media_type: str,
        target_count: int,
        user_settings: Any = None,
    ) -> list[dict[str, Any]]:
        """Fetch details for a batch of items in parallel."""
        final_results = []
        query_type = "movie" if media_type == "movie" else "tv"
        sem = asyncio.Semaphore(30)

        async def _fetch(tid: int):
            async with sem:
                try:
                    if query_type == "movie":
                        return await tmdb_service.get_movie_details(tid)
                    return await tmdb_service.get_tv_details(tid)
                except Exception:
                    return None

        valid_items = [it for it in items if it.get("id")]
        batch_size = 20

        for i in range(0, len(valid_items), batch_size):
            if len(final_results) >= target_count:
                break
            chunk = valid_items[i : i + batch_size]  # noqa
            tasks = [_fetch(it["id"]) for it in chunk]
            details_list = await asyncio.gather(*tasks)

            for details in details_list:
                if details:
                    formatted = await cls.format_for_stremio(details, media_type, user_settings)
                    if formatted:
                        final_results.append(formatted)
                if len(final_results) >= target_count:
                    break

        return final_results
