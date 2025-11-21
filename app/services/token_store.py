import json
import hmac
import hashlib
from typing import Any, Dict, Optional

import redis.asyncio as redis
from loguru import logger

from app.config import settings


class TokenStore:
    """Redis-backed store for user credentials and auth tokens."""

    def __init__(self) -> None:
        self._client: Optional[redis.Redis] = None

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
        return f"watchly:token:{hashed_token}"

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

    async def store_payload(self, payload: Dict[str, Any]) -> str:
        normalized = self._normalize_payload(payload)
        token = self._derive_token_value(normalized)
        hashed = self._hash_token(token)
        key = self._format_key(hashed)
        client = await self._get_client()
        value = json.dumps(normalized)
        if settings.TOKEN_TTL_SECONDS and settings.TOKEN_TTL_SECONDS > 0:
            await client.setex(key, settings.TOKEN_TTL_SECONDS, value)
            logger.info(
                "Stored credential payload with TTL %s seconds", settings.TOKEN_TTL_SECONDS
            )
        else:
            await client.set(key, value)
            logger.info("Stored credential payload without expiration")
        return token

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


token_store = TokenStore()
