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


class ProfileService:
    """Builds, updates, caches, and exposes user taste profiles."""

    def __init__(self, language: str = "en-US", tmdb_api_key: str | None = None):
        self.scoring_service = ScoringService()
        self.sampler = SmartSampler(self.scoring_service)
        tmdb_service = get_tmdb_service(language=language, api_key=tmdb_api_key)
        vectorizer = ItemVectorizer(tmdb_service)
        self.builder = ProfileBuilder(vectorizer)

    async def build_profile_from_library(
        self,
        library_items: dict,
        content_type: str,
        stremio_service: Any = None,
        auth_key: str | None = None,
    ) -> tuple[TasteProfile | None, set[int], set[str]]:
        """Build taste profile from library items and get watched sets."""
        watched_imdb, watched_tmdb = await RecommendationFiltering.get_exclusion_sets(
            stremio_service, library_items, auth_key
        )

        all_items = (
            library_items.get("loved", [])
            + library_items.get("liked", [])
            + library_items.get("watched", [])
            + library_items.get("added", [])
        )
        typed_items = [it for it in all_items if it.get("type") == content_type]

        if not typed_items:
            return None, watched_tmdb, watched_imdb

        library_items_dict = {
            "loved": [it for it in library_items.get("loved", []) if it.get("type") == content_type],
            "liked": [it for it in library_items.get("liked", []) if it.get("type") == content_type],
            "watched": [it for it in library_items.get("watched", []) if it.get("type") == content_type],
            "added": [it for it in library_items.get("added", []) if it.get("type") == content_type],
        }
        sampled = self.sampler.sample_items(library_items_dict, content_type)
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
        """Build profile incrementally if possible, fallback to full rebuild."""
        watched_imdb, watched_tmdb = await RecommendationFiltering.get_exclusion_sets(
            stremio_service, library_items, auth_key
        )

        all_items = (
            library_items.get("loved", [])
            + library_items.get("liked", [])
            + library_items.get("watched", [])
            + library_items.get("added", [])
        )
        typed_items = [it for it in all_items if it.get("type") == content_type]

        if not typed_items:
            return None, watched_tmdb, watched_imdb

        try:
            library_changed = await user_cache.has_library_changed(token, content_type, typed_items)

            if not library_changed:
                existing_profile = await user_cache.get_profile(token, content_type)
                if existing_profile:
                    return existing_profile, watched_tmdb, watched_imdb

            existing_profile = await user_cache.get_profile(token, content_type)

            if existing_profile:
                processed_ids = existing_profile.processed_items
                current_ids = {it.get("_id", it.get("id")) for it in typed_items if it.get("_id", it.get("id"))}
                is_legacy = not processed_ids and (existing_profile.genre_scores or existing_profile.director_scores)

                if not processed_ids.issubset(current_ids) or is_legacy:
                    reason = "Legacy profile detected" if is_legacy else "Items removed from library"
                    logger.debug(f"[{token[:8]}...] {reason}, falling back to full rebuild")
                else:
                    new_item_ids = current_ids - processed_ids

                    if not new_item_ids:
                        return existing_profile, watched_tmdb, watched_imdb

                    logger.debug(f"[{token[:8]}...] Found {len(new_item_ids)} new items, using incremental update")

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

                    sampled = self.sampler.sample_items(new_library_items_dict, content_type)

                    if not sampled:
                        return existing_profile, watched_tmdb, watched_imdb

                    updated_profile = await self.builder.update_profile_incrementally(
                        existing_profile, sampled, content_type=content_type
                    )

                    await user_cache.update_library_hash(token, content_type, typed_items)
                    return updated_profile, watched_tmdb, watched_imdb

        except Exception as e:
            logger.warning(f"[{token[:8]}...] Incremental update failed, falling back to full rebuild: {e}")

        logger.debug(f"[{token[:8]}...] Using full rebuild")
        profile, _, _ = await self.build_profile_from_library(library_items, content_type, stremio_service, auth_key)
        await user_cache.update_library_hash(token, content_type, typed_items)
        return profile, watched_tmdb, watched_imdb

    async def build_and_cache_profile(
        self,
        token: str,
        content_type: str,
        library_items: dict,
        stremio_service: Any = None,
        auth_key: str | None = None,
    ) -> tuple[TasteProfile | None, set[int], set[str]]:
        """Build profile data and cache the profile and watched sets."""
        profile, watched_tmdb, watched_imdb = await self.build_profile_incremental(
            library_items,
            content_type,
            token,
            stremio_service,
            auth_key,
        )
        await user_cache.set_profile_and_watched_sets(token, content_type, profile, watched_tmdb, watched_imdb)
        return profile, watched_tmdb, watched_imdb

    async def get_genre_whitelist(self, profile: TasteProfile, content_type: str) -> set[int]:
        """Get genre whitelist from the user's top genres in the profile."""
        try:
            if not profile:
                return set()

            top_genres = profile.get_top_genres(limit=GENRE_WHITELIST_LIMIT)
            return {int(genre_id) for genre_id, _ in top_genres}
        except Exception as e:
            logger.warning(f"Failed to build genre whitelist for {content_type}: {e}")
            return set()


ProfileIntegration = ProfileService
