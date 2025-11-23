import asyncio
from urllib.parse import unquote

from loguru import logger

from app.services.stremio_service import StremioService
from app.services.tmdb_service import TMDBService


def _parse_identifier(identifier: str) -> tuple[str | None, int | None]:
    """Parse Stremio identifier to extract IMDB ID and TMDB ID."""
    if not identifier:
        return None, None

    decoded = unquote(identifier)
    imdb_id: str | None = None
    tmdb_id: int | None = None

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
    4. Fetch full metadata from TMDB
    5. Return formatted recommendations
    """

    def __init__(self, stremio_service: StremioService | None = None):
        if stremio_service is None:
            raise ValueError("StremioService instance is required for personalized recommendations")
        self.tmdb_service = TMDBService()
        self.stremio_service = stremio_service
        self.per_item_limit = 20

    async def _fetch_metadata_for_items(self, items: list[dict], media_type: str) -> list[dict]:
        """
        Fetch detailed metadata for items directly from TMDB API and format for Stremio.
        """
        final_results = []
        # Ensure media_type is correct
        query_media_type = "movie" if media_type == "movie" else "tv"

        async def _fetch_details(tmdb_id: int):
            try:
                if query_media_type == "movie":
                    return await self.tmdb_service.get_movie_details(tmdb_id)
                else:
                    return await self.tmdb_service.get_tv_details(tmdb_id)
            except Exception as e:
                logger.warning(f"Failed to fetch details for TMDB ID {tmdb_id}: {e}")
                return None

        # Create tasks for all items to fetch details (needed for IMDB ID and full meta)
        # Filter out items without ID
        valid_items = [item for item in items if item.get("id")]
        tasks = [_fetch_details(item["id"]) for item in valid_items]

        if not tasks:
            return []

        details_results = await asyncio.gather(*tasks)

        for details in details_results:
            if not details:
                continue

            # Extract IMDB ID from external_ids
            external_ids = details.get("external_ids", {})
            imdb_id = external_ids.get("imdb_id")
            tmdb_id = details.get("id")

            # Prefer IMDB ID, fallback to TMDB ID
            stremio_id = imdb_id if imdb_id else f"tmdb:{tmdb_id}"

            # Construct Stremio meta object
            title = details.get("title") or details.get("name")
            if not title:
                continue

            # Image paths
            poster_path = details.get("poster_path")
            backdrop_path = details.get("backdrop_path")

            release_date = details.get("release_date") or details.get("first_air_date") or ""
            year = release_date[:4] if release_date else None

            meta_data = {
                "id": stremio_id,
                "type": "series" if media_type in ["tv", "series"] else "movie",
                "name": title,
                "poster": f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else None,
                "background": f"https://image.tmdb.org/t/p/original{backdrop_path}" if backdrop_path else None,
                "description": details.get("overview"),
                "releaseInfo": year,
                "imdbRating": str(details.get("vote_average", "")),
                "genres": [g.get("name") for g in details.get("genres", [])],
            }

            # Add runtime if available (Movie) or episode run time (TV)
            runtime = details.get("runtime")
            if not runtime and details.get("episode_run_time"):
                runtime = details.get("episode_run_time")[0]

            if runtime:
                meta_data["runtime"] = f"{runtime} min"

            final_results.append(meta_data)

        return final_results

    async def get_recommendations_for_item(self, item_id: str) -> list[dict]:
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
            # Default to movie if we can't determine type from ID
            media_type = "movie"

        # Safety check
        if not media_type:
            media_type = "movie"

        # Get recommendations (empty sets mean no library filtering)
        recommendations = await self._fetch_recommendations_from_tmdb(str(tmdb_id), media_type, self.per_item_limit)

        if not recommendations:
            logger.warning(f"No recommendations found for {item_id}")
            return []

        logger.info(f"Found {len(recommendations)} recommendations for {item_id}")
        return await self._fetch_metadata_for_items(recommendations, media_type)

    async def _fetch_recommendations_from_tmdb(self, item_id: str, media_type: str, limit: int) -> list[dict]:
        """
        Fetch recommendations from TMDB for a given TMDB ID.
        """
        if isinstance(item_id, int):
            item_id = str(item_id)

        if item_id.startswith("tt"):
            tmdb_id, detected_type = await self.tmdb_service.find_by_imdb_id(item_id)
            if not tmdb_id:
                logger.warning(f"No TMDB ID found for {item_id}")
                return []
            if detected_type:
                media_type = detected_type
        elif item_id.startswith("tmdb:"):
            tmdb_id = int(item_id.split(":")[1])
        else:
            tmdb_id = item_id

        recommendation_response = await self.tmdb_service.get_recommendations(tmdb_id, media_type)
        recommended_items = recommendation_response.get("results", [])
        if not recommended_items:
            return []
        return recommended_items[:limit]

    async def get_recommendations(
        self,
        content_type: str | None = None,
        source_items_limit: int = 2,
        recommendations_per_source: int = 5,
        max_results: int = 50,
        include_watched: bool = False,
    ) -> list[dict]:
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
        8. Fetch full metadata for final list

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
        watched_imdb_ids: set[str] = set()
        watched_tmdb_ids: set[int] = set()
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
                source_item.get("_id"),
                source_item.get("type"),
                recommendations_per_source,
            )
            for source_item in source_items
        ]
        all_recommendation_results = await asyncio.gather(*recommendation_tasks, return_exceptions=True)

        # Step 6: Aggregate recommendations from all source items
        # Use dictionary to deduplicate by IMDB ID and combine scores
        unique_recommendations: dict[str, dict] = {}  # Key: IMDB ID, Value: Full recommendation data

        flat_recommendations = []
        for recommendation_batch in all_recommendation_results:
            if isinstance(recommendation_batch, Exception):
                logger.warning(f"Error processing source item: {recommendation_batch}")
                continue

            for recommendation in recommendation_batch:
                flat_recommendations.append(recommendation)

        # Step 7: Deduplicate and filter BEFORE fetching full meta
        filtered_tmdb_items = []
        seen_tmdb_ids = set()

        for item in flat_recommendations:
            tmdb_id = item.get("id")
            if not tmdb_id or tmdb_id in seen_tmdb_ids or tmdb_id in watched_tmdb_ids:
                continue

            # Simple dedupe based on TMDB ID first
            seen_tmdb_ids.add(tmdb_id)

            # We'll do the full scoring logic after fetching meta, but we can prep unique list now
            filtered_tmdb_items.append(item)

            # Optimization: If we have way too many, cut off early
            if len(filtered_tmdb_items) >= max_results * 2:
                break

        # Step 8: Fetch full metadata
        final_recommendations = await self._fetch_metadata_for_items(filtered_tmdb_items, content_type)

        for meta_data in final_recommendations:
            imdb_id = meta_data.get("imdb_id") or meta_data.get("id")

            # Skip if already watched or no IMDB ID
            if not imdb_id or imdb_id in watched_imdb_ids:
                continue

            if imdb_id not in unique_recommendations:
                # Base score from IMDB rating
                try:
                    score = float(meta_data.get("imdbRating", 0))
                except (ValueError, TypeError):
                    score = 0.0
                meta_data["_score"] = score
                unique_recommendations[imdb_id] = meta_data
            else:
                # Boost score if recommended by multiple source items
                existing_recommendation = unique_recommendations[imdb_id]
                try:
                    additional_score = float(meta_data.get("imdbRating", 0))
                except (ValueError, TypeError):
                    additional_score = 0.0
                existing_recommendation["_score"] = existing_recommendation.get("_score", 0) + additional_score

            # Early exit if we have enough results
            if len(unique_recommendations) >= max_results:
                break

        # Step 9: Sort by score (higher score = more relevant, appears from more sources)
        sorted_recommendations = sorted(
            unique_recommendations.values(),
            key=lambda x: x.get("_score", 0),
            reverse=True,
        )

        logger.info(f"Generated {len(sorted_recommendations)} unique recommendations")
        return sorted_recommendations

    async def get_recommendations_for_genre(self, genre_id: str, media_type: str) -> list[dict]:
        """
        Get recommendations for a specific genre.
        """
        # parse genre ids first
        # remove watchly.genre. prefix
        genre_id = genre_id.replace("watchly.genre.", "")

        # genre_id params, replace - with , and _ with |
        genre_id_params = genre_id.replace("-", ",").replace("_", "|")
        # now call discover api
        # get recommendations from tmdb api
        recommendations = await self.tmdb_service.get_discover(
            media_type=media_type,
            with_genres=genre_id_params,
            sort_by="popularity.desc",
        )
        recommendations = recommendations.get("results", [])

        return await self._fetch_metadata_for_items(recommendations, media_type)
