from app.services.rpdb import RPDBService


class MetadataFetcher:
    """Handles fetching and formatting metadata from TMDB."""

    def __init__(self, tmdb_service, user_settings=None):
        self.tmdb_service = tmdb_service
        self.user_settings = user_settings

    async def fetch_item_details(self, tmdb_id: int, media_type: str) -> dict | None:
        try:
            if media_type == "movie":
                return await self.tmdb_service.get_movie_details(tmdb_id)
            else:
                return await self.tmdb_service.get_tv_details(tmdb_id)
        except Exception:
            return None

    def format_for_stremio(self, details: dict, media_type: str) -> dict | None:
        if not details:
            return None

        # ID Resolution
        external = details.get("external_ids", {})
        imdb_id = external.get("imdb_id")
        tmdb_id = details.get("id")

        # Primary ID for Stremio
        stremio_id = imdb_id if imdb_id else f"tmdb:{tmdb_id}"
        if not stremio_id:
            return None

        title = details.get("title") or details.get("name")
        if not title:
            return None

        # Image Handling
        poster_path = details.get("poster_path")
        backdrop_path = details.get("backdrop_path")

        poster_url = None
        if self.user_settings and self.user_settings.rpdb_key:
            poster_url = RPDBService.get_poster_url(self.user_settings.rpdb_key, stremio_id)
        elif poster_path:
            poster_url = f"https://image.tmdb.org/t/p/w500{poster_path}"

        background_url = f"https://image.tmdb.org/t/p/original{backdrop_path}" if backdrop_path else None

        release_date = details.get("release_date") or details.get("first_air_date") or ""
        year = release_date[:4] if release_date else None

        genres = [g.get("name") for g in details.get("genres", [])]

        return {
            "id": stremio_id,
            "type": "series" if media_type in ("tv", "series") else "movie",
            "name": title,
            "poster": poster_url,
            "background": background_url,
            "description": details.get("overview"),
            "releaseInfo": year,
            "imdbRating": str(details.get("vote_average", "")),
            "genres": genres,
            # Internal fields for downstream use
            "_tmdb_id": tmdb_id,
            "_imdb_id": imdb_id,
            "vote_average": details.get("vote_average"),
            "vote_count": details.get("vote_count"),
        }
