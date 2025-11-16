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
    """Service for generating recommendations based on user's Stremio library."""

    def __init__(self, stremio_service: Optional[StremioService] = None):
        self.tmdb_service = TMDBService()
        self.stremio_service = stremio_service or StremioService()
        self.per_item_limit = 20

    async def get_recommendations_for_item(self, item_id: str) -> List[Dict]:
        # find tmdb id
        tmdb_id, media_type = await self.tmdb_service.find_by_imdb_id(item_id)
        if not tmdb_id:
            logger.warning(f"No TMDB ID found for {item_id}")
            return []
        # get details by tmdb id
        recommendations = await self._get_recommendations_for_seed(tmdb_id, media_type, self.per_item_limit)
        if not recommendations:
            logger.warning(f"No recommendations found for {item_id}")
            return []
        logger.info(f"Found {len(recommendations)} recommendations for {item_id}")
        return recommendations

    async def get_recommendations(
        self,
        content_type: Optional[str] = None,
        seed_limit: int = 2,
        per_seed_limit: int = 5,
        max_results: int = 50,
    ) -> List[Dict]:
        """Get recommendations based on user's Stremio library."""
        if not content_type:
            logger.warning("content_type must be specified (movie or series)")
            return []

        logger.info(f"Getting recommendations for {content_type}")

        # Fetch library items once (returns both watched and loved)
        library_data = await self.stremio_service.get_library_items()
        loved_items = library_data.get("loved", [])
        watched_items = library_data.get("watched", [])

        if not loved_items:
            logger.warning(
                "No loved library items found, returning empty recommendations"
            )
            return []

        # Filter by content type - only use items matching the requested type
        loved_items = [item for item in loved_items if item.get("type") == content_type]

        if not loved_items:
            logger.warning(f"No loved {content_type} items found in library")
            return []

        # Get last 10 items (most recent, already sorted by modification time descending)
        seeds = loved_items[:seed_limit]
        logger.info(
            f"Using {len(seeds)} most recent loved {content_type} items as seeds"
        )

        # Build library IMDB ID set to exclude (all watched items, regardless of type)
        # Parse identifiers (synchronous operation, but fast)
        library_imdb_ids: Set[str] = set()
        for item in watched_items:
            imdb_id, _ = _parse_identifier(item.get("_id", ""))
            if imdb_id:
                library_imdb_ids.add(imdb_id)

        logger.info(f"Built exclusion set with {len(library_imdb_ids)} watched items")

        # Collect recommendations
        all_recommendations: Dict[str, Dict] = {}  # Key: IMDB ID

        # Process seeds in parallel for better performance
        seed_tasks = [
            self._process_seed(seed, content_type, per_seed_limit, library_imdb_ids)
            for seed in seeds
        ]
        seed_results = await asyncio.gather(*seed_tasks, return_exceptions=True)

        # Aggregate results from all seeds
        for seed_result in seed_results:
            if isinstance(seed_result, Exception):
                logger.warning(f"Error processing seed: {seed_result}")
                continue

            for rec in seed_result:
                # rec is the full addon meta response, extract IMDB ID from meta
                meta_data = rec.get("meta", {})
                rec_imdb_id = meta_data.get("_imdb_id") or meta_data.get("imdb_id")
                if rec_imdb_id and rec_imdb_id not in library_imdb_ids:
                    if rec_imdb_id not in all_recommendations:
                        all_recommendations[rec_imdb_id] = rec
                    else:
                        # Update score if this recommendation appears from multiple seeds
                        existing = all_recommendations[rec_imdb_id]
                        existing_meta = existing.get("meta", {})
                        existing_meta["_score"] = existing_meta.get(
                            "_score", 0
                        ) + meta_data.get("_score", 0)

            # Limit total results
            if len(all_recommendations) >= max_results:
                break

        # Sort by score and return
        sorted_recommendations = sorted(
            all_recommendations.values(),
            key=lambda x: x.get("meta", {}).get("_score", 0),
            reverse=True,
        )

        result = sorted_recommendations
        logger.info(f"Generated {len(result)} recommendations")
        return result

    async def _process_seed(
        self,
        seed: Dict,
        content_type: str,
        per_seed_limit: int,
        library_imdb_ids: Set[str],
    ) -> List[Dict]:
        """Process a single seed and return recommendations."""
        imdb_id, tmdb_id = _parse_identifier(seed.get("_id", ""))
        seed_type = seed.get("type")

        if not imdb_id:
            # Try to find IMDB ID from TMDB if we have TMDB ID
            if tmdb_id:
                details = await self._get_details_by_tmdb(tmdb_id, seed_type)
                if details:
                    imdb_id = details.get("imdb_id")
            else:
                return []

        # If we don't have TMDB ID, find it from IMDB
        if not tmdb_id and imdb_id:
            tmdb_id, found_media_type = await self.tmdb_service.find_by_imdb_id(imdb_id)
            if not tmdb_id:
                return []
            media_type = found_media_type
        elif tmdb_id:
            # Ensure media_type matches the requested content_type
            media_type = "movie" if seed_type == "movie" else "tv"
        else:
            return []

        # Double-check: only process if media_type matches requested content_type
        expected_media_type = "movie" if content_type == "movie" else "tv"
        if media_type != expected_media_type:
            logger.info(
                f"Skipping seed {imdb_id}: media_type {media_type} doesn't match {content_type}"
            )
            return []

        # Get recommendations for this seed
        recommendations = await self._get_recommendations_for_seed(
            tmdb_id, media_type, per_seed_limit
        )
        return recommendations

    async def _get_details_by_tmdb(
        self, tmdb_id: int, content_type: str
    ) -> Optional[Dict]:
        """Get details by TMDB ID and extract IMDB ID."""
        try:
            if content_type == "movie":
                details = await self.tmdb_service.get_movie_details(tmdb_id)
            else:
                details = await self.tmdb_service.get_tv_details(tmdb_id)

            # Extract IMDB ID
            imdb_id = details.get("imdb_id")
            if not imdb_id and content_type == "series":
                imdb_id = details.get("external_ids", {}).get("imdb_id")

            if imdb_id:
                details["imdb_id"] = imdb_id
                return details
            return None
        except Exception as e:
            logger.info(
                f"Error getting details for TMDB {tmdb_id} ({content_type}): {e}"
            )
            return None

    async def _get_recommendations_for_seed(
        self, tmdb_id: int, media_type: str, limit: int
    ) -> List[Dict]:
        """Get first N recommendations for a single seed from TMDB."""
        try:
            # Get recommendations from TMDB (returns first page of results)
            rec_data = await self.tmdb_service.get_recommendations(tmdb_id, media_type)
            print(rec_data)
            all_results = rec_data.get("results", [])

            # Get IMDB IDs in parallel (need to fetch basic details to get IMDB ID)
            # Fetch more items to account for missing IMDB IDs, but limit to first results
            items_to_process = all_results[
                : limit * 2
            ]  # Process 2x limit to account for missing IMDB IDs
            detail_tasks = []
            item_scores = {}

            for item in items_to_process:
                item_tmdb_id = item.get("id")
                if not item_tmdb_id:
                    continue
                item_scores[item_tmdb_id] = item.get("vote_average", 0) or 0

                # Fetch details in parallel
                if media_type == "movie":
                    detail_tasks.append(
                        self.tmdb_service.get_movie_details(item_tmdb_id)
                    )
                else:
                    detail_tasks.append(self.tmdb_service.get_tv_details(item_tmdb_id))

            if not detail_tasks:
                return []

            # Get all details in parallel
            detail_results = await asyncio.gather(*detail_tasks, return_exceptions=True)

            # Extract IMDB IDs
            imdb_ids_to_fetch = []
            scores_map = {}
            for item, detail_result in zip(items_to_process, detail_results):
                if isinstance(detail_result, Exception):
                    continue

                item_tmdb_id = item.get("id")
                if not item_tmdb_id:
                    continue

                imdb_id = detail_result.get("imdb_id")
                if not imdb_id and media_type == "tv":
                    imdb_id = detail_result.get("external_ids", {}).get("imdb_id")

                if imdb_id:
                    imdb_ids_to_fetch.append((imdb_id, media_type))
                    scores_map[imdb_id] = item_scores.get(item_tmdb_id, 0)

                if len(imdb_ids_to_fetch) >= limit:
                    break

            if not imdb_ids_to_fetch:
                return []

            # Fetch addon metadata in parallel
            stremio_type = "movie" if media_type == "movie" else "series"
            meta_tasks = [
                self.tmdb_service.get_addon_meta(stremio_type, imdb_id)
                for imdb_id, _ in imdb_ids_to_fetch
            ]

            meta_results = await asyncio.gather(*meta_tasks, return_exceptions=True)

            # Process results
            results = []
            for (imdb_id, _), meta_result in zip(imdb_ids_to_fetch, meta_results):
                if isinstance(meta_result, Exception):
                    logger.info(
                        f"Error fetching addon meta for {imdb_id}: {meta_result}"
                    )
                    continue

                if meta_result and meta_result.get("meta"):
                    # Ensure id is set to IMDB ID (Stremio requirement)
                    meta_result["meta"]["id"] = imdb_id
                    # Store score and IMDB ID in the meta for later use
                    meta_result["meta"]["_imdb_id"] = imdb_id
                    meta_result["meta"]["_score"] = scores_map.get(imdb_id, 0)
                    meta_result["meta"]["_media_type"] = media_type
                    # Return the full addon response (with meta key)
                    results.append(meta_result)

                if len(results) >= limit:
                    break

            logger.info(
                f"Found {len(results)} recommendations for seed {tmdb_id} ({media_type})"
            )
            return results
        except Exception as e:
            logger.warning(
                f"Error getting recommendations for seed {tmdb_id} ({media_type}): {e}"
            )
            return []
