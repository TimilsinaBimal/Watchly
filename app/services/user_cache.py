import json
import time
from typing import Any

from loguru import logger

from app.core.constants import (
    CATALOG_KEY,
    LIBRARY_ITEMS_KEY,
    PROFILE_KEY,
    PROFILE_SCORING_VERSION,
    USER_CACHE_TTL_SECONDS,
    WATCHED_SETS_KEY,
)
from app.core.security import redact_token
from app.models.library import LibraryCollection
from app.models.profile import TasteProfile
from app.services.redis_service import redis_service


class UserCacheService:
    @staticmethod
    def _library_items_key(token: str) -> str:
        """Generate cache key for library items."""
        return LIBRARY_ITEMS_KEY.format(token=token)

    @staticmethod
    def _profile_key(token: str, content_type: str) -> str:
        """Generate cache key for profile."""
        return PROFILE_KEY.format(token=token, content_type=content_type)

    @staticmethod
    def _watched_sets_key(token: str, content_type: str) -> str:
        """Generate cache key for watched sets."""
        return WATCHED_SETS_KEY.format(token=token, content_type=content_type)

    @staticmethod
    def _library_buckets_key(token: str, content_type: str) -> str:
        """Generate cache key for the rating-bucket map behind the cached profile."""
        return f"watchly:library_buckets:v1:{token}:{content_type}"

    # Library Items Methods

    async def get_library_items(self, token: str) -> LibraryCollection | None:
        """Get cached library items for a user."""
        key = self._library_items_key(token)
        cached = await redis_service.get(key)

        if cached:
            try:
                data = json.loads(cached)
                # Refresh TTL on read so active users' caches stay warm.
                await redis_service.expire(key, USER_CACHE_TTL_SECONDS)
                return LibraryCollection.model_validate(data)
            except (json.JSONDecodeError, Exception) as e:
                logger.warning(f"Failed to decode cached library items for {redact_token(token)}...: {e}")
                return None

        return None

    async def set_library_items(self, token: str, library_items: LibraryCollection) -> None:
        """Cache library items for a user."""
        key = self._library_items_key(token)
        await redis_service.set(key, library_items.model_dump_json(by_alias=True), USER_CACHE_TTL_SECONDS)
        logger.debug(f"[{redact_token(token)}...] Cached library items")

        await self.invalidate_all_catalogs(token)

    async def invalidate_library_items(self, token: str) -> None:
        """
        Invalidate cached library items for a user.

        Args:
            token: User token
        """
        key = self._library_items_key(token)
        await redis_service.delete(key)
        logger.debug(f"[{redact_token(token)}...] Invalidated library items cache")

    # Profile Methods

    async def get_profile(self, token: str, content_type: str) -> TasteProfile | None:
        """
        Get cached profile for a user and content type.

        Args:
            token: User token
            content_type: Content type (movie or series)

        Returns:
            TasteProfile instance, or None if not cached or built by older scoring
        """
        key = self._profile_key(token, content_type)
        cached = await redis_service.get(key)

        if cached:
            try:
                profile = TasteProfile.model_validate_json(cached)
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning(f"Failed to decode cached profile for {redact_token(token)}.../{content_type}: {e}")
                return None

            # Dropped here rather than at the build sites: catalog_service reads
            # profiles straight out of the cache, so a version check anywhere else
            # would be bypassed on the hot path.
            if profile.scoring_version < PROFILE_SCORING_VERSION:
                logger.info(
                    f"[{redact_token(token)}...] Dropping {content_type} profile from scoring "
                    f"v{profile.scoring_version}; rebuilding at v{PROFILE_SCORING_VERSION}"
                )
                await redis_service.delete(key)
                return None

            await redis_service.expire(key, USER_CACHE_TTL_SECONDS)
            return profile

        return None

    async def set_profile(self, token: str, content_type: str, profile: TasteProfile) -> None:
        """
        Cache profile for a user and content type.

        Args:
            token: User token
            content_type: Content type (movie or series)
            profile: TasteProfile instance to cache
        """
        key = self._profile_key(token, content_type)
        await redis_service.set(key, profile.model_dump_json(), USER_CACHE_TTL_SECONDS)
        logger.debug(f"[{redact_token(token)}...] Cached profile for {content_type}")

    async def invalidate_profile(self, token: str, content_type: str) -> None:
        """
        Invalidate cached profile for a user and content type.

        Args:
            token: User token
            content_type: Content type (movie or series)
        """
        key = self._profile_key(token, content_type)
        await redis_service.delete(key)
        logger.debug(f"[{redact_token(token)}...] Invalidated profile cache for {content_type}")

    # Watched Sets Methods

    async def get_watched_sets(self, token: str, content_type: str) -> tuple[set[int], set[str]] | None:
        """
        Get cached watched sets for a user and content type.

        Args:
            token: User token
            content_type: Content type (movie or series)

        Returns:
            Tuple of (watched_tmdb set, watched_imdb set), or None if not cached
        """
        key = self._watched_sets_key(token, content_type)
        cached = await redis_service.get(key)

        if cached:
            try:
                data = json.loads(cached)
                watched_tmdb = set(data.get("watched_tmdb", []))
                watched_imdb = set(data.get("watched_imdb", []))
                await redis_service.expire(key, USER_CACHE_TTL_SECONDS)
                return (watched_tmdb, watched_imdb)
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                logger.warning(f"Failed to decode cached watched sets for {redact_token(token)}.../{content_type}: {e}")
                return None

        return None

    async def set_watched_sets(
        self,
        token: str,
        content_type: str,
        watched_tmdb: set[int],
        watched_imdb: set[str],
    ) -> None:
        """
        Cache watched sets for a user and content type.

        Args:
            token: User token
            content_type: Content type (movie or series)
            watched_tmdb: Set of watched TMDB IDs
            watched_imdb: Set of watched IMDb IDs
        """
        key = self._watched_sets_key(token, content_type)
        data = {
            "watched_tmdb": list(watched_tmdb),
            "watched_imdb": list(watched_imdb),
        }
        await redis_service.set(key, json.dumps(data), USER_CACHE_TTL_SECONDS)
        logger.debug(f"[{redact_token(token)}...] Cached watched sets for {content_type}")

    async def invalidate_watched_sets(self, token: str, content_type: str) -> None:
        """
        Invalidate cached watched sets for a user and content type.

        Args:
            token: User token
            content_type: Content type (movie or series)
        """
        key = self._watched_sets_key(token, content_type)
        await redis_service.delete(key)
        logger.debug(f"[{redact_token(token)}...] Invalidated watched sets cache for {content_type}")

    # Combined Methods

    async def get_profile_and_watched_sets(
        self, token: str, content_type: str
    ) -> tuple[TasteProfile | None, set[int], set[str]] | None:
        """
        Get both cached profile and watched sets for a user and content type.

        Args:
            token: User token
            content_type: Content type (movie or series)

        Returns:
            Tuple of (profile, watched_tmdb, watched_imdb), or None if either is not cached.
            Returns None if either profile or watched sets are missing.
        """
        profile = await self.get_profile(token, content_type)
        watched_sets = await self.get_watched_sets(token, content_type)

        if profile is None or watched_sets is None:
            return None

        watched_tmdb, watched_imdb = watched_sets
        return (profile, watched_tmdb, watched_imdb)

    # Library Change Detection Methods

    @staticmethod
    def bucket_map(typed: LibraryCollection) -> dict[str, str]:
        """Map every item of one content type to the rating bucket it sits in.

        Buckets, not just ids: for Trakt and Simkl the rating *is* the signal
        (>=9 loved, 7-8.9 liked), so an id-only digest reads a re-rating as no
        change at all. Written last-wins in strength order so an item that
        somehow appears in two buckets resolves to the strongest.
        """
        return {
            **{i.id: "a" for i in typed.added},
            **{i.id: "w" for i in typed.watched},
            **{i.id: "k" for i in typed.liked},
            **{i.id: "l" for i in typed.loved},
        }

    async def get_library_buckets(self, token: str, content_type: str) -> dict[str, str] | None:
        """The bucket map the cached profile was built from, or None if unknown."""
        cached = await redis_service.get(self._library_buckets_key(token, content_type))
        if not cached:
            return None
        try:
            return json.loads(cached)
        except json.JSONDecodeError:
            return None

    async def set_library_buckets(self, token: str, content_type: str, typed: LibraryCollection) -> None:
        """Record the bucket map the profile was just built from."""
        key = self._library_buckets_key(token, content_type)
        await redis_service.set(key, json.dumps(self.bucket_map(typed)), USER_CACHE_TTL_SECONDS)
        logger.debug(f"[{redact_token(token)}...] Updated library buckets for {content_type}")

    async def invalidate_library_buckets(self, token: str, content_type: str) -> None:
        await redis_service.delete(self._library_buckets_key(token, content_type))

    async def set_profile_and_watched_sets(
        self,
        token: str,
        content_type: str,
        profile: TasteProfile | None,
        watched_tmdb: set[int],
        watched_imdb: set[str],
    ) -> None:
        """
        Cache both profile and watched sets for a user and content type.

        Args:
            token: User token
            content_type: Content type (movie or series)
            profile: TasteProfile instance to cache (can be None)
            watched_tmdb: Set of watched TMDB IDs
            watched_imdb: Set of watched IMDb IDs
        """
        if profile:
            await self.set_profile(token, content_type, profile)
        await self.set_watched_sets(token, content_type, watched_tmdb, watched_imdb)

        # Invalidate all catalog caches when profile is updated
        # This ensures catalogs are regenerated with fresh profile data
        await self.invalidate_all_catalogs(token)

    # Invalidation Methods

    async def invalidate_all_user_data(self, token: str) -> None:
        """
        Invalidate all cached data for a user (library items, profiles, watched sets, catalogs).

        Args:
            token: User token
        """
        await self.invalidate_library_items(token)
        for content_type in ["movie", "series"]:
            await self.invalidate_profile(token, content_type)
            await self.invalidate_watched_sets(token, content_type)
            await self.invalidate_library_buckets(token, content_type)
        await self.invalidate_all_catalogs(token)
        logger.debug(f"[{redact_token(token)}...] Invalidated all user data cache")

    async def get_catalog(self, token: str, type: str, id: str) -> tuple[dict[str, Any], int] | None:
        """
        Get cached catalog for a user and content type.

        Args:
            token: User token
            type: Content type (movie or series)
            id: Catalog ID

        Returns:
            Tuple of (catalog_data, timestamp) or None if not found
        """
        key = CATALOG_KEY.format(token=token, type=type, id=id)
        cached = await redis_service.get(key)
        if cached:
            try:
                data = json.loads(cached)
                # Handle new format with timestamp wrapper
                if "data" in data and "created_at" in data:
                    return data["data"], data["created_at"]
                # Handle legacy format (raw catalog dict)
                # Return 0 timestamp to force refresh if it exceeds window
                return data, 0
            except json.JSONDecodeError:
                return None
        return None

    async def set_catalog(
        self,
        token: str,
        type: str,
        id: str,
        catalog: dict[str, Any],
        ttl: int | None = None,
    ) -> None:
        """
        Cache catalog for a user and content type.

        Args:
            token: User token
            type: Content type (movie or series)
            id: Catalog ID
            catalog: Catalog dictionary to cache
            ttl: Time to live for the cache (in seconds)
        """
        key = CATALOG_KEY.format(token=token, type=type, id=id)
        # Store with timestamp for stale-while-revalidate logic
        wrapped_data = {
            "data": catalog,
            "created_at": int(time.time()),
        }
        await redis_service.set(key, json.dumps(wrapped_data), ttl)
        logger.debug(f"[{redact_token(token)}...] Cached catalog for {type}/{id}")

    async def invalidate_catalog(self, token: str, type: str, id: str) -> None:
        """
        Invalidate cached catalog for a user and content type.

        Args:
            token: User token
            type: Content type (movie or series)
            id: Catalog ID
        """
        key = CATALOG_KEY.format(token=token, type=type, id=id)
        await redis_service.delete(key)
        logger.debug(f"[{redact_token(token)}...] Invalidated catalog cache for {type}/{id}")

    async def invalidate_all_catalogs(self, token: str) -> None:
        """
        Invalidate all cached catalogs for a user.

        This should be called when user data (library items, profiles) is updated
        to ensure catalogs are regenerated with fresh data.

        Args:
            token: User token
        """
        pattern = f"watchly:catalog:{token}:*"
        deleted_count = await redis_service.delete_by_pattern(pattern)
        if deleted_count > 0:
            logger.debug(f"[{redact_token(token)}...] Invalidated {deleted_count} catalog cache(s)")
        else:
            logger.debug(f"[{redact_token(token)}...] No catalog caches found to invalidate")


user_cache = UserCacheService()
