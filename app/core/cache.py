import json
from typing import Any, Optional

import redis.asyncio as redis
from loguru import logger

from app.core.config import settings


class RedisCache:
    """
    Generic Redis cache wrapper for the application.
    Handles connection pooling, serialization, and error handling.
    """

    _instance: Optional["RedisCache"] = None

    def __init__(self):
        self._client: redis.Redis | None = None

    @classmethod
    def get_instance(cls) -> "RedisCache":
        if cls._instance is None:
            cls._instance = RedisCache()
        return cls._instance

    async def get_client(self) -> redis.Redis:
        if self._client is None:
            if not settings.REDIS_URL:
                raise RuntimeError("REDIS_URL is not configured")

            logger.info("Initializing Redis Cache Client")
            self._client = redis.from_url(
                settings.REDIS_URL,
                decode_responses=True,  # Auto-decode to strings
                encoding="utf-8",
                socket_connect_timeout=5,
                socket_timeout=5,
                max_connections=getattr(settings, "REDIS_MAX_CONNECTIONS", 100),
                health_check_interval=30,
            )
        return self._client

    async def close(self):
        if self._client:
            await self._client.close()
            self._client = None

    async def get(self, key: str) -> Any:
        try:
            client = await self.get_client()
            return await client.get(key)
        except Exception as e:
            logger.error(f"Redis GET failed for {key}: {e}")
            return None

    async def get_json(self, key: str) -> Any:
        raw = await self.get(key)
        if not raw:
            return None
        try:
            return json.loads(raw)
        except Exception:
            return None

    async def set(self, key: str, value: Any, ttl: int = None):
        try:
            client = await self.get_client()
            val = value if isinstance(value, str) else json.dumps(value)
            if ttl:
                await client.setex(key, ttl, val)
            else:
                await client.set(key, val)
        except Exception as e:
            logger.error(f"Redis SET failed for {key}: {e}")

    async def delete(self, key: str):
        try:
            client = await self.get_client()
            await client.delete(key)
        except Exception:
            pass


cache = RedisCache.get_instance()
