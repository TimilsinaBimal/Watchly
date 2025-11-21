import httpx
from typing import Dict, Optional, Tuple
from loguru import logger
from app.config import settings
from app.utils import cached_api_call


class TMDBService:
    """Service for interacting with The Movie Database (TMDB) API."""

    def __init__(self):
        self.api_key = settings.TMDB_API_KEY
        self.base_url = "https://api.themoviedb.org/3"
        self.addon_url = settings.TMDB_ADDON_URL
        # Reuse HTTP client for connection pooling and better performance
        self._client: Optional[httpx.AsyncClient] = None
        self._addon_client: Optional[httpx.AsyncClient] = None
        if not self.api_key:
            logger.warning(
                "TMDB_API_KEY is not configured. Catalog endpoints will fail until the key is provided."
            )

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the main TMDB API client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=10.0,
                limits=httpx.Limits(max_keepalive_connections=20, max_connections=100),
            )
        return self._client

    async def _get_addon_client(self) -> httpx.AsyncClient:
        """Get or create the addon API client."""
        if self._addon_client is None:
            self._addon_client = httpx.AsyncClient(
                timeout=10.0,
                limits=httpx.Limits(max_keepalive_connections=20, max_connections=100),
            )
        return self._addon_client

    async def close(self):
        """Close HTTP clients."""
        if self._client:
            await self._client.aclose()
            self._client = None
        if self._addon_client:
            await self._addon_client.aclose()
            self._addon_client = None

    @cached_api_call
    async def get_addon_meta(self, type: str, id: str) -> Dict:
        """Get addon metadata for a specific type and ID."""
        url = f"{self.addon_url}/meta/{type}/{id}.json"
        client = await self._get_addon_client()
        response = await client.get(url)
        response.raise_for_status()
        return response.json()

    async def _make_request(self, endpoint: str, params: Optional[Dict] = None) -> Dict:
        """Make a request to the TMDB API."""
        if not self.api_key:
            raise RuntimeError(
                "TMDB_API_KEY is not configured. Set the environment variable to enable TMDB requests."
            )
        url = f"{self.base_url}{endpoint}"
        default_params = {"api_key": self.api_key, "language": "en-US"}

        if params:
            default_params.update(params)

        try:
            client = await self._get_client()
            response = await client.get(url, params=default_params)
            response.raise_for_status()

            # Check if response has content
            if not response.text:
                logger.warning(f"TMDB API returned empty response for {endpoint}")
                return {}

            try:
                return response.json()
            except ValueError as e:
                logger.error(
                    f"TMDB API returned invalid JSON for {endpoint}: {e}. Response: {response.text[:200]}"
                )
                return {}
        except httpx.HTTPStatusError as e:
            logger.error(
                f"TMDB API error for {endpoint}: {e.response.status_code} - {e.response.text[:200]}"
            )
            raise
        except httpx.RequestError as e:
            logger.error(f"TMDB API request error for {endpoint}: {e}")
            raise

    @cached_api_call
    async def find_by_imdb_id(
        self, imdb_id: str
    ) -> Tuple[Optional[int], Optional[str]]:
        """Find TMDB ID and type by IMDB ID."""
        try:
            endpoint = f"/find/{imdb_id}"
            params = {"external_source": "imdb_id"}
            data = await self._make_request(endpoint, params)

            # Check if we got valid data
            if not data or not isinstance(data, dict):
                logger.info(f"Invalid response data for IMDB {imdb_id}")
                return None, None

            # Check movie results first
            movie_results = data.get("movie_results", [])
            if movie_results and len(movie_results) > 0:
                tmdb_id = movie_results[0].get("id")
                if tmdb_id:
                    logger.info(f"Found TMDB movie {tmdb_id} for IMDB {imdb_id}")
                    return tmdb_id, "movie"

            # Check TV results
            tv_results = data.get("tv_results", [])
            if tv_results and len(tv_results) > 0:
                tmdb_id = tv_results[0].get("id")
                if tmdb_id:
                    logger.info(f"Found TMDB TV {tmdb_id} for IMDB {imdb_id}")
                    return tmdb_id, "tv"

            logger.info(f"No TMDB result found for IMDB {imdb_id}")
            return None, None
        except httpx.HTTPStatusError:
            # Already logged in _make_request
            return None, None
        except httpx.RequestError:
            # Already logged in _make_request
            return None, None
        except Exception as e:
            logger.warning(f"Unexpected error finding TMDB ID for IMDB {imdb_id}: {e}")
            return None, None

    @cached_api_call
    async def get_movie_details(self, movie_id: int) -> Dict:
        """Get details of a specific movie with credits and external IDs."""
        params = {"append_to_response": "credits,external_ids"}
        return await self._make_request(f"/movie/{movie_id}", params=params)

    @cached_api_call
    async def get_tv_details(self, tv_id: int) -> Dict:
        """Get details of a specific TV series with credits and external IDs."""
        params = {"append_to_response": "credits,external_ids"}
        return await self._make_request(f"/tv/{tv_id}", params=params)

    @cached_api_call
    async def get_recommendations(
        self, tmdb_id: int, media_type: str, page: int = 1
    ) -> Dict:
        """Get recommendations based on TMDB ID and media type."""
        params = {"page": page}
        endpoint = f"/{media_type}/{tmdb_id}/recommendations"
        return await self._make_request(endpoint, params=params)

    @cached_api_call
    async def get_similar(self, tmdb_id: int, media_type: str, page: int = 1) -> Dict:
        """Get similar content based on TMDB ID and media type."""
        params = {"page": page}
        endpoint = f"/{media_type}/{tmdb_id}/similar"
        return await self._make_request(endpoint, params=params)

    @cached_api_call
    async def get_discover(self, media_type: str, params: dict[str, str]) -> Dict:
        """Get discover content based on params."""
        media_type = "movie" if media_type == "movie" else "tv"
        endpoint = f"/discover/{media_type}"
        return await self._make_request(endpoint, params=params)
