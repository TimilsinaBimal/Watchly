import asyncio
from typing import List, Dict, Optional, Set, Tuple
from urllib.parse import unquote
from loguru import logger
from app.services.tmdb_service import TMDBService
from app.services.stremio_service import StremioService


def _parse_identifier(identifier: str) -> Tuple[Optional[str], Optional[int]]:
    """Parse Stremio identifier to extract IMDB ID and TMDB ID."""
    if not identifier:
        return None, None

    decoded = unquote(identifier)
    imdb_id: Optional[str] = None
    tmdb_id: Optional[int] = None

    for token in decoded.split(","):
        token = token.strip()
        if not token:
            continue
        if token.startswith("tt") and imdb_id is None:
            imdb_id = token
        elif token.startswith("tmdb:") and tmdb_id is None:
            try:
                tmdb_id = int(token.split(":", 1)[1])
            except (ValueError, IndexError):
                continue
        if imdb_id and tmdb_id is not None:
            break

    return imdb_id, tmdb_id


class RecommendationService:
    """
    Service for generating recommendations based on user's Stremio library.

    The recommendation flow:
    1. Get user's loved and watched items from Stremio library
    2. Use loved items as "source items" to find similar content from TMDB
    3. Filter out items already in the user's watched library
    4. Fetch full metadata from TMDB addon
    5. Return formatted recommendations
    """

    def __init__(self, stremio_service: Optional[StremioService] = None):
        if stremio_service is None:
            raise ValueError("StremioService instance is required for personalized recommendations")
        self.tmdb_service = TMDBService()
        self.stremio_service = stremio_service
        self.per_item_limit = 20

    async def _fetch_catlogs_from_tmdb_addon(self, items: list[dict], media_type: str):
        final_results = []
        media_type = "movie" if media_type == "movie" else "series"
        # now fetch addon meta for each recommendation
        fetch_meta_tasks = [
            self.tmdb_service.get_addon_meta(media_type, f"tmdb:{item.get('id')}") for item in items
        ]
        addon_meta_results = await asyncio.gather(*fetch_meta_tasks, return_exceptions=True)
        for addon_meta in addon_meta_results:
            if isinstance(addon_meta, Exception):
                logger.warning(f"Error processing source item: {addon_meta}")
                continue
            meta_data = addon_meta.get("meta", {})
            if not hasattr(meta_data, "id"):
                meta_data["id"] = meta_data.get("imdb_id")
            final_results.append(meta_data)
        return final_results

    async def get_recommendations_for_item(self, item_id: str) -> List[Dict]:
        """
        Get recommendations for a specific item by IMDB ID.

        This is used when user clicks on a specific item to see "similar" recommendations.
        No library filtering is applied - we show all recommendations.
        """
        # Convert IMDB ID to TMDB ID (needed for TMDB recommendations API)
        if item_id.startswith("tt"):
            tmdb_id, media_type = await self.tmdb_service.find_by_imdb_id(item_id)
            if not tmdb_id:
                logger.warning(f"No TMDB ID found for {item_id}")
                return []
        else:
            tmdb_id = item_id.split(":")[1]

        media_type = "movie" if media_type == "movie" else "tv"

        # Get recommendations (empty sets mean no library filtering)
        recommendations = await self._fetch_recommendations_from_tmdb(tmdb_id, media_type, self.per_item_limit)

        if not recommendations:
            logger.warning(f"No recommendations found for {item_id}")
            return []

        logger.info(f"Found {len(recommendations)} recommendations for {item_id}")
        return await self._fetch_catlogs_from_tmdb_addon(recommendations, media_type)

    async def _fetch_recommendations_from_tmdb(self, item_id: str, media_type: str, limit: int) -> List[Dict]:
        """
        Fetch recommendations from TMDB for a given TMDB ID.
        """
        if isinstance(item_id, int):
            item_id = str(item_id)

        if item_id.startswith("tt"):
            tmdb_id, media_type = await self.tmdb_service.find_by_imdb_id(item_id)
            if not tmdb_id:
                logger.warning(f"No TMDB ID found for {item_id}")
                return []
        elif item_id.startswith("tmdb:"):
            tmdb_id = int(item_id.split(":")[1])
        else:
            tmdb_id = item_id

        media_type = "movie" if media_type == "movie" else "tv"

        recommendation_response = await self.tmdb_service.get_recommendations(tmdb_id, media_type)
        recommended_items = recommendation_response.get("results", [])
        if not recommended_items:
            return []
        return recommended_items[:limit]

    async def get_recommendations(
        self,
        content_type: Optional[str] = None,
        source_items_limit: int = 2,
        recommendations_per_source: int = 5,
        max_results: int = 50,
        include_watched: bool = False,
    ) -> List[Dict]:
        """
        Get recommendations based on user's Stremio library.

        Process:
        1. Get user's loved items from library (these are "source items" we use to find similar content)
        2. If include_watched is True, also include watched items as source items
        3. Get user's watched items (these will be excluded from recommendations)
        4. For each source item, fetch recommendations from TMDB
        5. Filter out items already watched
        6. Aggregate and deduplicate recommendations
        7. Sort by relevance score

        Args:
            content_type: "movie" or "series"
            source_items_limit: How many items to use as sources (default: 2)
            recommendations_per_source: How many recommendations per source item (default: 5)
            max_results: Maximum total recommendations to return (default: 50)
            include_watched: If True, include watched items as source items in addition to loved items (default: False)
        """
        if not content_type:
            logger.warning("content_type must be specified (movie or series)")
            return []

        logger.info(f"Getting recommendations for {content_type} (include_watched: {include_watched})")

        # Step 1: Fetch user's library items (both watched and loved)
        library_data = await self.stremio_service.get_library_items()
        loved_items = library_data.get("loved", [])
        watched_items = library_data.get("watched", [])

        # Step 2: Build source items list based on config
        if include_watched:
            all_source_items = watched_items
            logger.info(f"Using watched items ({len(watched_items)}) as sources")
        else:
            # Only use loved items
            all_source_items = loved_items
            logger.info(f"Using only loved items ({len(loved_items)}) as sources")

        if not all_source_items:
            logger.warning(
                f"No {'loved or watched' if include_watched else 'loved'} library items found, returning empty"
                " recommendations"
            )
            return []

        # Step 3: Filter source items by content type (only use movies for movie recommendations)
        source_items_of_type = [item for item in all_source_items if item.get("type") == content_type]

        if not source_items_of_type:
            logger.warning(f"No {content_type} items found in library")
            return []

        # Step 4: Select most recent items as "source items" for finding recommendations
        # (These are the items we'll use to find similar content)
        # Sort by modification time (most recent first) if available
        source_items_of_type.sort(key=lambda x: x.get("_mtime", ""), reverse=True)
        source_items = source_items_of_type[:source_items_limit]
        logger.info(f"Using {len(source_items)} most recent {content_type} items as sources")

        # Step 4: Build exclusion sets (IMDB IDs and TMDB IDs) for watched items
        # We don't want to recommend things the user has already watched
        watched_imdb_ids: Set[str] = set()
        watched_tmdb_ids: Set[int] = set()
        for item in watched_items:
            imdb_id, tmdb_id = _parse_identifier(item.get("_id", ""))
            if imdb_id:
                watched_imdb_ids.add(imdb_id)
            if tmdb_id:
                watched_tmdb_ids.add(tmdb_id)

        logger.info(f"Built exclusion sets: {len(watched_imdb_ids)} IMDB IDs, {len(watched_tmdb_ids)} TMDB IDs")

        # Step 5: Process each source item in parallel to get recommendations
        # Each source item will generate its own set of recommendations
        recommendation_tasks = [
            self._fetch_recommendations_from_tmdb(
                source_item.get("_id"), source_item.get("type"), recommendations_per_source
            )
            for source_item in source_items
        ]
        all_recommendation_results = await asyncio.gather(*recommendation_tasks, return_exceptions=True)

        # Step 6: Aggregate recommendations from all source items
        # Use dictionary to deduplicate by IMDB ID and combine scores
        unique_recommendations: Dict[str, Dict] = {}  # Key: IMDB ID, Value: Full recommendation data

        flat_recommendations = []
        for recommendation_batch in all_recommendation_results:
            if isinstance(recommendation_batch, Exception):
                logger.warning(f"Error processing source item: {recommendation_batch}")
                continue

            for recommendation in recommendation_batch:
                flat_recommendations.append(recommendation)

        final_recommendations = await self._fetch_catlogs_from_tmdb_addon(flat_recommendations, content_type)

        for meta_data in final_recommendations:
            imdb_id = meta_data.get("imdb_id") or meta_data.get("id")

            # Skip if already watched or no IMDB ID
            if not imdb_id or imdb_id in watched_imdb_ids:
                continue

            if imdb_id not in unique_recommendations:
                meta_data["_score"] = float(meta_data.get("imdbRating", 0))
                unique_recommendations[imdb_id] = meta_data
            else:
                # Boost score if recommended by multiple source items
                existing_recommendation = unique_recommendations[imdb_id]
                existing_recommendation["_score"] = existing_recommendation.get("_score", 0) + float(
                    meta_data.get("imdbRating", 0)
                )

            # Early exit if we have enough results
            if len(unique_recommendations) >= max_results:
                break

        # Step 7: Sort by score (higher score = more relevant, appears from more sources)
        sorted_recommendations = sorted(
            unique_recommendations.values(),
            key=lambda x: x.get("_score", 0),
            reverse=True,
        )

        logger.info(f"Generated {len(sorted_recommendations)} unique recommendations")
        return sorted_recommendations

    async def get_recommendations_for_genre(self, genre_id: str, media_type: str) -> List[Dict]:
        """
        Get recommendations for a specific genre.
        """
        # parse genre ids first
        # remove watchly.genre. prefix
        genre_id = genre_id.replace("watchly.genre.", "")

        # genre_id params, replace - with , and _ with |
        genre_id_params = genre_id.replace("-", ",").replace("_", "|")
        # build payloads
        params = {
            "sort_by": "popularity.desc",
            "with_genres": genre_id_params,
        }

        # now call discover api
        # get recommendations from tmdb api
        recommendations = await self.tmdb_service.get_discover(media_type=media_type, params=params)
        recommendations = recommendations.get("results", [])

        return await self._fetch_catlogs_from_tmdb_addon(recommendations, media_type)
