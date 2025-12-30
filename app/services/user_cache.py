import json
from typing import Any

from loguru import logger

from app.core.constants import CATALOG_KEY, LIBRARY_ITEMS_KEY, PROFILE_KEY, WATCHED_SETS_KEY
from app.core.security import redact_token
from app.models.taste_profile import TasteProfile
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

    # Library Items Methods

    async def get_library_items(self, token: str) -> dict[str, Any] | None:
        """
        Get cached library items for a user.

        Args:
            token: User token

        Returns:
            Library items dictionary, or None if not cached
        """
        key = self._library_items_key(token)
        cached = await redis_service.get(key)

        if cached:
            try:
                return json.loads(cached)
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to decode cached library items for {redact_token(token)}...: {e}")
                return None

        return None

    async def set_library_items(self, token: str, library_items: dict[str, Any]) -> None:
        """
        Cache library items for a user.

        Args:
            token: User token
            library_items: Library items dictionary to cache
        """
        key = self._library_items_key(token)
        await redis_service.set(key, json.dumps(library_items))
        logger.debug(f"[{redact_token(token)}...] Cached library items")

        # Invalidate all catalog caches when library items are updated
        # This ensures catalogs are regenerated with fresh library data
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
            TasteProfile instance, or None if not cached
        """
        key = self._profile_key(token, content_type)
        cached = await redis_service.get(key)

        if cached:
            try:
                return TasteProfile.model_validate_json(cached)
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning(f"Failed to decode cached profile for {redact_token(token)}.../{content_type}: {e}")
                return None

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
        await redis_service.set(key, profile.model_dump_json())
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
                return (watched_tmdb, watched_imdb)
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                logger.warning(f"Failed to decode cached watched sets for {redact_token(token)}.../{content_type}: {e}")
                return None

        return None

    async def set_watched_sets(
        self, token: str, content_type: str, watched_tmdb: set[int], watched_imdb: set[str]
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
        await redis_service.set(key, json.dumps(data))
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
        await self.invalidate_all_catalogs(token)
        logger.debug(f"[{redact_token(token)}...] Invalidated all user data cache")

    async def get_catalog(self, token: str, type: str, id: str) -> dict[str, Any] | None:
        """
        Get cached catalog for a user and content type.

        Args:
            token: User token
            type: Content type (movie or series)
            id: Catalog ID
        """
        key = CATALOG_KEY.format(token=token, type=type, id=id)
        cached = await redis_service.get(key)
        if cached:
            return json.loads(cached)
        return None

    async def set_catalog(
        self, token: str, type: str, id: str, catalog: dict[str, Any], ttl: int | None = None
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
        await redis_service.set(key, json.dumps(catalog), ttl)
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
