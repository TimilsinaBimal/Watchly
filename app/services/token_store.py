import json
import hmac
import hashlib
from collections.abc import AsyncIterator
from typing import Any, Dict, Optional

import redis.asyncio as redis
from loguru import logger

from app.config import settings


class TokenStore:
    """Redis-backed store for user credentials and auth tokens."""

    KEY_PREFIX = "watchly:token:"

    def __init__(self) -> None:
        self._client: Optional[redis.Redis] = None
        if not settings.REDIS_URL:
            logger.warning(
                "REDIS_URL is not set. Token storage will fail until a Redis instance is configured."
            )
        if not settings.TOKEN_SALT or settings.TOKEN_SALT == "change-me":
            logger.warning(
                "TOKEN_SALT is missing or using the default placeholder. Set a strong value to secure tokens."
            )

    def _ensure_secure_salt(self) -> None:
        if not settings.TOKEN_SALT or settings.TOKEN_SALT == "change-me":
            logger.error(
                "Refusing to store credentials because TOKEN_SALT is unset or using the insecure default."
            )
            raise RuntimeError(
                "Server misconfiguration: TOKEN_SALT must be set to a non-default value before storing credentials."
            )

    async def _get_client(self) -> redis.Redis:
        if self._client is None:
            self._client = redis.from_url(
                settings.REDIS_URL, decode_responses=True, encoding="utf-8"
            )
        return self._client

    def _hash_token(self, token: str) -> str:
        secret = settings.TOKEN_SALT.encode("utf-8")
        return hmac.new(secret, msg=token.encode("utf-8"), digestmod=hashlib.sha256).hexdigest()

    def _format_key(self, hashed_token: str) -> str:
        return f"{self.KEY_PREFIX}{hashed_token}"

    def _normalize_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "username": (payload.get("username") or "").strip() or None,
            "password": payload.get("password") or None,
            "authKey": (payload.get("authKey") or "").strip() or None,
            "includeWatched": bool(payload.get("includeWatched", False)),
        }

    def _derive_token_value(self, payload: Dict[str, Any]) -> str:
        canonical = {
            "username": payload.get("username") or "",
            "password": payload.get("password") or "",
            "authKey": payload.get("authKey") or "",
            "includeWatched": bool(payload.get("includeWatched", False)),
        }
        serialized = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
        secret = settings.TOKEN_SALT.encode("utf-8")
        return hmac.new(secret, serialized.encode("utf-8"), hashlib.sha256).hexdigest()

    async def store_payload(self, payload: Dict[str, Any]) -> tuple[str, bool]:
        self._ensure_secure_salt()
        normalized = self._normalize_payload(payload)
        token = self._derive_token_value(normalized)
        hashed = self._hash_token(token)
        key = self._format_key(hashed)
        client = await self._get_client()
        existing = await client.exists(key)
        value = json.dumps(normalized)
        if settings.TOKEN_TTL_SECONDS and settings.TOKEN_TTL_SECONDS > 0:
            await client.setex(key, settings.TOKEN_TTL_SECONDS, value)
            logger.info(
                "Stored credential payload with TTL %s seconds", settings.TOKEN_TTL_SECONDS
            )
        else:
            await client.set(key, value)
            logger.info("Stored credential payload without expiration")
        return token, not bool(existing)

    async def get_payload(self, token: str) -> Optional[Dict[str, Any]]:
        hashed = self._hash_token(token)
        key = self._format_key(hashed)
        client = await self._get_client()
        raw = await client.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Failed to decode cached payload for token")
            return None

    async def delete_token(self, token: str) -> None:
        hashed = self._hash_token(token)
        key = self._format_key(hashed)
        client = await self._get_client()
        await client.delete(key)

    async def iter_payloads(self) -> AsyncIterator[tuple[str, Dict[str, Any]]]:
        """Iterate over all stored payloads, yielding key and payload."""
        try:
            client = await self._get_client()
        except (redis.RedisError, OSError) as exc:
            logger.warning("Skipping credential iteration; Redis unavailable: %s", exc)
            return

        pattern = f"{self.KEY_PREFIX}*"
        try:
            async for key in client.scan_iter(match=pattern):
                try:
                    raw = await client.get(key)
                except (redis.RedisError, OSError) as exc:
                    logger.warning("Failed to fetch payload for %s: %s", key, exc)
                    continue
                if raw is None:
                    continue
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    logger.warning("Failed to decode cached payload for key %s", key)
                    continue
                yield key, payload
        except (redis.RedisError, OSError) as exc:
            logger.warning("Failed to scan credential tokens: %s", exc)


token_store = TokenStore()
