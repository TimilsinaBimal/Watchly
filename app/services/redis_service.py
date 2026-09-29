from typing import Any

import redis.asyncio as redis
from loguru import logger

from app.core.config import settings


class RedisService:
    def __init__(self) -> None:
        self._client: redis.Redis | None = None

    async def get_client(self) -> redis.Redis:
        if self._client is None:
            logger.info("Creating Redis client for RedisService")
            self._client = redis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
                encoding="utf-8",
                socket_connect_timeout=5,
                socket_timeout=5,
                max_connections=settings.REDIS_MAX_CONNECTIONS,
                health_check_interval=30,
                socket_keepalive=True,
            )
        return self._client

    async def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        try:
            client = await self.get_client()
            str_value = str(value)
            if ttl is not None:
                result = await client.setex(key, ttl, str_value)
            else:
                result = await client.set(key, str_value)
            return bool(result)
        except (redis.RedisError, OSError) as exc:
            logger.error(f"Redis set failed: {exc}")
            return False

    async def get(self, key: str) -> str | None:
        try:
            client = await self.get_client()
            value = await client.get(key)
            return value
        except (redis.RedisError, OSError) as exc:
            logger.error(f"Redis get failed: {exc}")
            return None

    async def delete(self, key: str) -> bool:
        try:
            client = await self.get_client()
            result = await client.delete(key)
            return bool(result)
        except (redis.RedisError, OSError) as exc:
            logger.error(f"Redis delete failed: {exc}")
            return False

    async def getex(self, key: str, ttl: int) -> str | None:
        """Get a value and refresh its TTL in one round trip."""
        try:
            client = await self.get_client()
            return await client.getex(key, ex=ttl)
        except (redis.RedisError, OSError) as exc:
            logger.error(f"Redis getex failed: {exc}")
            return None

    async def exists(self, key: str) -> bool:
        try:
            client = await self.get_client()
            result = await client.exists(key)
            return bool(result)
        except (redis.RedisError, OSError) as exc:
            logger.error(f"Redis exists failed: {exc}")
            return False

    async def delete_by_pattern(self, pattern: str) -> int:
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
            logger.error(f"Redis delete_by_pattern failed: {exc}")
            return 0

    async def set_nx(self, key: str, value: Any, ttl: int | None = None) -> bool:
        try:
            client = await self.get_client()
            str_value = str(value)
            result = await client.set(key, str_value, ex=ttl, nx=True)
            return bool(result)
        except (redis.RedisError, OSError) as exc:
            logger.error(f"Redis set_nx failed: {exc}")
            return False

    async def close(self) -> None:
        if self._client is not None:
            try:
                await self._client.close()
                logger.info("RedisService client closed")
            except Exception as exc:
                logger.warning(f"Failed to close RedisService client: {exc}")
            finally:
                self._client = None


redis_service = RedisService()
