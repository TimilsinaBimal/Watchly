from typing import Any

import redis.asyncio as redis
from loguru import logger

from app.core.config import settings


class RedisService:
    def __init__(self) -> None:
        self._client: redis.Redis | None = None
        if not settings.REDIS_URL:
            logger.warning("REDIS_URL is not set. Redis operations will fail until configured.")

    async def get_client(self) -> redis.Redis:
        if self._client is None:
            logger.info("Creating Redis client for RedisService")
            self._client = redis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
                encoding="utf-8",
                socket_connect_timeout=5,
                socket_timeout=5,
                max_connections=getattr(settings, "REDIS_MAX_CONNECTIONS", 100),
                health_check_interval=30,
                socket_keepalive=True,
            )
        return self._client

    async def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        """Store a value in Redis with optional TTL.

        Args:
            key: The key to store the value under
            value: The value to store (will be converted to string)
            ttl: Optional time-to-live in seconds. If None, key never expires.

        Returns:
            True if successful, False otherwise
        """
        try:
            client = await self.get_client()
            str_value = str(value)
            if ttl is not None:
                result = await client.setex(key, ttl, str_value)
            else:
                result = await client.set(key, str_value)
            return bool(result)
        except (redis.RedisError, OSError) as exc:
            logger.error(f"Failed to set key '{key}' in Redis: {exc}")
            return False

    async def get(self, key: str) -> str | None:
        """Get a value from Redis by key.

        Args:
            key: The key to retrieve

        Returns:
            The value as a string, or None if key doesn't exist or error occurred
        """
        try:
            client = await self.get_client()
            value = await client.get(key)
            return value
        except (redis.RedisError, OSError) as exc:
            logger.error(f"Failed to get key '{key}' from Redis: {exc}")
            return None

    async def delete(self, key: str) -> bool:
        """Delete a key from Redis.

        Args:
            key: The key to delete

        Returns:
            True if key was deleted, False otherwise
        """
        try:
            client = await self.get_client()
            result = await client.delete(key)
            return bool(result)
        except (redis.RedisError, OSError) as exc:
            logger.error(f"Failed to delete key '{key}' from Redis: {exc}")
            return False

    async def exists(self, key: str) -> bool:
        """Check if a key exists in Redis.

        Args:
            key: The key to check

        Returns:
            True if key exists, False otherwise
        """
        try:
            client = await self.get_client()
            result = await client.exists(key)
            return bool(result)
        except (redis.RedisError, OSError) as exc:
            logger.error(f"Failed to check existence of key '{key}' in Redis: {exc}")
            return False

    async def delete_by_pattern(self, pattern: str) -> int:
        """Delete all keys matching a pattern.

        Args:
            pattern: Redis key pattern (e.g., "watchly:catalog:token123:*")

        Returns:
            Number of keys deleted
        """
        try:
            client = await self.get_client()
            deleted_count = 0
            keys_to_delete = []
            async for key in client.scan_iter(match=pattern, count=500):
                keys_to_delete.append(key)
                if len(keys_to_delete) >= 500:
                    deleted_count += await client.delete(*keys_to_delete)
                    keys_to_delete = []
            if keys_to_delete:
                deleted_count += await client.delete(*keys_to_delete)
            return deleted_count
        except (redis.RedisError, OSError) as exc:
            logger.error(f"Failed to delete keys matching pattern '{pattern}' in Redis: {exc}")
            return 0

    async def close(self) -> None:
        """Close and disconnect the Redis client"""
        if self._client is not None:
            try:
                await self._client.close()
                logger.info("RedisService client closed")
            except Exception as exc:
                logger.warning(f"Failed to close RedisService client: {exc}")
            finally:
                self._client = None


redis_service = RedisService()
