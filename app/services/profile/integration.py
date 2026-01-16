from typing import Any

from loguru import logger

from app.models.taste_profile import TasteProfile
from app.services.profile.builder import ProfileBuilder
from app.services.profile.constants import GENRE_WHITELIST_LIMIT
from app.services.profile.sampling import SmartSampler
from app.services.profile.vectorizer import ItemVectorizer
from app.services.recommendation.filtering import RecommendationFiltering
from app.services.scoring import ScoringService
from app.services.tmdb.service import get_tmdb_service
from app.services.user_cache import user_cache


class ProfileIntegration:
    """
    Helper class to integrate taste profile services with existing systems.
    """

    def __init__(self, language: str = "en-US"):
        self.scoring_service = ScoringService()
        self.sampler = SmartSampler(self.scoring_service)
        tmdb_service = get_tmdb_service(language=language)
        vectorizer = ItemVectorizer(tmdb_service)
        self.builder = ProfileBuilder(vectorizer)

    async def build_profile_from_library(
        self,
        library_items: dict,
        content_type: str,
        stremio_service: Any = None,
        auth_key: str | None = None,
    ) -> tuple[TasteProfile | None, set[int], set[str]]:
        """
        Build taste profile from library items and get watched sets.

        Args:
            library_items: Library items dict from Stremio
            content_type: Content type (movie/series)
            stremio_service: Stremio service (optional, for watched sets)
            auth_key: Auth key (optional, for watched sets)

        Returns:
            Tuple of (profile, watched_tmdb, watched_imdb)
        """
        # Get watched sets
        watched_imdb, watched_tmdb = await RecommendationFiltering.get_exclusion_sets(
            stremio_service, library_items, auth_key
        )

        # Convert library items to ScoredItems
        all_items = (
            library_items.get("loved", [])
            + library_items.get("liked", [])
            + library_items.get("watched", [])
            + library_items.get("added", [])
        )
        typed_items = [it for it in all_items if it.get("type") == content_type]

        if not typed_items:
            return None, watched_tmdb, watched_imdb

        # Sample items using SmartSampler (it expects raw library items dict)
        library_items_dict = {
            "loved": [it for it in library_items.get("loved", []) if it.get("type") == content_type],
            "liked": [it for it in library_items.get("liked", []) if it.get("type") == content_type],
            "watched": [it for it in library_items.get("watched", []) if it.get("type") == content_type],
            "added": [it for it in library_items.get("added", []) if it.get("type") == content_type],
        }
        sampled = self.sampler.sample_items(library_items_dict, content_type)

        # Build profile
        profile = await self.builder.build_profile(sampled, content_type=content_type)

        return profile, watched_tmdb, watched_imdb

    async def build_profile_incremental(
        self,
        library_items: dict,
        content_type: str,
        token: str,
        stremio_service: Any = None,
        auth_key: str | None = None,
    ) -> tuple[TasteProfile | None, set[int], set[str]]:
        """
        Build profile incrementally if possible, fallback to full rebuild.

        Args:
            library_items: Library items dict from Stremio
            content_type: Content type (movie/series)
            token: User token for change detection
            stremio_service: Stremio service (optional, for watched sets)
            auth_key: Auth key (optional, for watched sets)

        Returns:
            Tuple of (profile, watched_tmdb, watched_imdb)
        """
        # Get watched sets
        watched_imdb, watched_tmdb = await RecommendationFiltering.get_exclusion_sets(
            stremio_service, library_items, auth_key
        )

        # Convert library items to ScoredItems for change detection
        all_items = (
            library_items.get("loved", [])
            + library_items.get("liked", [])
            + library_items.get("watched", [])
            + library_items.get("added", [])
        )
        typed_items = [it for it in all_items if it.get("type") == content_type]

        if not typed_items:
            return None, watched_tmdb, watched_imdb

        # Check if we can use incremental update
        try:
            # Check if library has changed
            library_changed = await user_cache.has_library_changed(token, content_type, typed_items)

            if not library_changed:
                # No changes - return existing profile
                existing_profile = await user_cache.get_profile(token, content_type)
                if existing_profile:
                    return existing_profile, watched_tmdb, watched_imdb

            # Try to get existing profile for incremental update
            existing_profile = await user_cache.get_profile(token, content_type)

            if existing_profile:
                # Check for removals or new items
                processed_ids = existing_profile.processed_items
                current_ids = {it.get("_id", it.get("id")) for it in typed_items if it.get("_id", it.get("id"))}

                # Check if this is a legacy profile (has scores but no processed_items)
                is_legacy = not processed_ids and (existing_profile.genre_scores or existing_profile.director_scores)

                # If items were removed, or it's a legacy profile, we must do a full rebuild
                if not processed_ids.issubset(current_ids) or is_legacy:
                    reason = "Legacy profile detected" if is_legacy else "Items removed from library"
                    logger.debug(f"[{token[:8]}...] {reason}, falling back to full rebuild")
                    # Fall through to full rebuild
                else:
                    # Identify new items
                    new_item_ids = current_ids - processed_ids

                    if not new_item_ids:
                        # No new items and no removals (maybe just metadata changed?)
                        # We can just return the existing profile
                        return existing_profile, watched_tmdb, watched_imdb

                    logger.debug(f"[{token[:8]}...] Found {len(new_item_ids)} new items, using incremental update")

                    # Filter library items to only new ones for sampling
                    new_library_items_dict = {
                        "loved": [
                            it
                            for it in library_items.get("loved", [])
                            if it.get("type") == content_type and (it.get("_id") or it.get("id")) in new_item_ids
                        ],
                        "liked": [
                            it
                            for it in library_items.get("liked", [])
                            if it.get("type") == content_type and (it.get("_id") or it.get("id")) in new_item_ids
                        ],
                        "watched": [
                            it
                            for it in library_items.get("watched", [])
                            if it.get("type") == content_type and (it.get("_id") or it.get("id")) in new_item_ids
                        ],
                        "added": [
                            it
                            for it in library_items.get("added", [])
                            if it.get("type") == content_type and (it.get("_id") or it.get("id")) in new_item_ids
                        ],
                    }

                    # Sample only new items
                    sampled = self.sampler.sample_items(new_library_items_dict, content_type)

                    if not sampled:
                        # Should not happen if new_item_ids is not empty, but just in case
                        return existing_profile, watched_tmdb, watched_imdb

                    # Update existing profile incrementally
                    updated_profile = await self.builder.update_profile_incrementally(
                        existing_profile, sampled, content_type=content_type
                    )

                    # Update library hash to mark as processed
                    await user_cache.update_library_hash(token, content_type, typed_items)

                    return updated_profile, watched_tmdb, watched_imdb

        except Exception as e:
            logger.warning(f"[{token[:8]}...] Incremental update failed, falling back to full rebuild: {e}")

        # Fallback to full rebuild
        logger.debug(f"[{token[:8]}...] Using full rebuild")
        profile_tuple = await self.build_profile_from_library(library_items, content_type, stremio_service, auth_key)
        profile, _, _ = profile_tuple

        # Update library hash after successful build
        await user_cache.update_library_hash(token, content_type, typed_items)

        return profile, watched_tmdb, watched_imdb

    async def get_genre_whitelist(
        self,
        profile: TasteProfile,
        content_type: str,
    ) -> set[int]:
        """
        Get genre whitelist from user's top genres in profile.

        Args:
            profile: Taste profile
            content_type: Content type (movie/series)

        Returns:
            Set of top genre IDs
        """
        try:
            if not profile:
                whitelist = set()
            else:
                # Get top genres
                top_genres = profile.get_top_genres(limit=GENRE_WHITELIST_LIMIT)
                whitelist = {int(genre_id) for genre_id, _ in top_genres}
                return whitelist
        except Exception as e:
            logger.warning(f"Failed to build genre whitelist for {content_type}: {e}")
            return set()
