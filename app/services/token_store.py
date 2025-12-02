import base64
import hashlib
import hmac
import json
from collections.abc import AsyncIterator
from typing import Any

import redis.asyncio as redis
from cachetools import TTLCache
from cryptography.fernet import Fernet, InvalidToken
from loguru import logger

from app.core.config import settings


class TokenStore:
    """Redis-backed store for user credentials and auth tokens."""

    KEY_PREFIX = settings.REDIS_TOKEN_KEY

    def __init__(self) -> None:
        self._client: redis.Redis | None = None
        self._cipher: Fernet | None = None
        # Cache decrypted payloads for 1 day (86400s) to reduce Redis hits
        # Max size 5000 allows many active users without eviction
        self._payload_cache: TTLCache = TTLCache(maxsize=5000, ttl=86400)

        if not settings.REDIS_URL:
            logger.warning("REDIS_URL is not set. Token storage will fail until a Redis instance is configured.")
        if not settings.TOKEN_SALT or settings.TOKEN_SALT == "change-me":
            logger.warning(
                "TOKEN_SALT is missing or using the default placeholder. Set a strong value to secure tokens."
            )

    def _ensure_secure_salt(self) -> None:
        if not settings.TOKEN_SALT or settings.TOKEN_SALT == "change-me":
            logger.error("Refusing to store credentials because TOKEN_SALT is unset or using the insecure default.")
            raise RuntimeError(
                "Server misconfiguration: TOKEN_SALT must be set to a non-default value before storing credentials."
            )

    def _get_cipher(self) -> Fernet:
        """Get or create Fernet cipher instance based on TOKEN_SALT."""
        if self._cipher is None:
            # Derive a 32-byte key from TOKEN_SALT using SHA256, then URL-safe base64 encode it
            # This ensures we always have a valid Fernet key regardless of the salt's format
            key_bytes = hashlib.sha256(settings.TOKEN_SALT.encode()).digest()
            fernet_key = base64.urlsafe_b64encode(key_bytes)
            self._cipher = Fernet(fernet_key)
        return self._cipher

    async def _get_client(self) -> redis.Redis:
        if self._client is None:
            self._client = redis.from_url(settings.REDIS_URL, decode_responses=True, encoding="utf-8")
        return self._client

    def _hash_token(self, token: str) -> str:
        secret = settings.TOKEN_SALT.encode("utf-8")
        return hmac.new(secret, msg=token.encode("utf-8"), digestmod=hashlib.sha256).hexdigest()

    def _format_key(self, hashed_token: str) -> str:
        return f"{self.KEY_PREFIX}{hashed_token}"

    def _normalize_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "username": (payload.get("username") or "").strip() or None,
            "password": payload.get("password") or None,
            "authKey": (payload.get("authKey") or "").strip() or None,
            "includeWatched": bool(payload.get("includeWatched", False)),
        }

    def _derive_token_value(self, payload: dict[str, Any]) -> str:
        canonical = {
            "username": payload.get("username") or "",
            "password": payload.get("password") or "",
            "authKey": payload.get("authKey") or "",
            "includeWatched": bool(payload.get("includeWatched", False)),
        }
        serialized = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
        secret = settings.TOKEN_SALT.encode("utf-8")
        return hmac.new(secret, serialized.encode("utf-8"), hashlib.sha256).hexdigest()

    def derive_token(self, payload: dict[str, Any]) -> str:
        """Public wrapper to derive token from payload."""
        normalized = self._normalize_payload(payload)
        return self._derive_token_value(normalized)

    async def store_payload(self, payload: dict[str, Any]) -> tuple[str, bool]:
        self._ensure_secure_salt()
        normalized = self._normalize_payload(payload)
        token = self._derive_token_value(normalized)
        hashed = self._hash_token(token)
        key = self._format_key(hashed)

        # JSON Encode -> Encrypt -> Store
        json_str = json.dumps(normalized)
        encrypted_value = self._get_cipher().encrypt(json_str.encode()).decode("utf-8")

        client = await self._get_client()
        existing = await client.exists(key)

        if settings.TOKEN_TTL_SECONDS and settings.TOKEN_TTL_SECONDS > 0:
            await client.setex(key, settings.TOKEN_TTL_SECONDS, encrypted_value)
            logger.info(
                f"Stored encrypted credential payload with TTL {settings.TOKEN_TTL_SECONDS} seconds",
            )
        else:
            await client.set(key, encrypted_value)
            logger.info("Stored encrypted credential payload without expiration")

        # Cache the new payload immediately to avoid next-read hit
        self._payload_cache[token] = normalized

        return token, not bool(existing)

    async def get_payload(self, token: str) -> dict[str, Any] | None:
        # Check local LRU cache first
        if token in self._payload_cache:
            return self._payload_cache[token]

        hashed = self._hash_token(token)
        key = self._format_key(hashed)
        client = await self._get_client()
        encrypted_raw = await client.get(key)

        if encrypted_raw is None:
            return None

        try:
            # Decrypt -> JSON Decode
            decrypted_json = self._get_cipher().decrypt(encrypted_raw.encode()).decode("utf-8")
            payload = json.loads(decrypted_json)

            # Cache for subsequent reads
            self._payload_cache[token] = payload
            return payload
        except (InvalidToken, json.JSONDecodeError, UnicodeDecodeError):
            logger.warning("Failed to decrypt or decode cached payload for token. Key might have changed.")
            return None

    async def delete_token(self, token: str) -> None:
        hashed = self._hash_token(token)
        key = self._format_key(hashed)
        client = await self._get_client()
        await client.delete(key)

        # Invalidate local cache
        if token in self._payload_cache:
            del self._payload_cache[token]

    async def iter_payloads(self) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """Iterate over all stored payloads, yielding key and payload."""
        try:
            client = await self._get_client()
        except (redis.RedisError, OSError) as exc:
            logger.warning(f"Skipping credential iteration; Redis unavailable: {exc}")
            return

        pattern = f"{self.KEY_PREFIX}*"
        cipher = self._get_cipher()

        try:
            async for key in client.scan_iter(match=pattern):
                try:
                    encrypted_raw = await client.get(key)
                except (redis.RedisError, OSError) as exc:
                    logger.warning(f"Failed to fetch payload for {key}: {exc}")
                    continue

                if encrypted_raw is None:
                    continue

                try:
                    decrypted_json = cipher.decrypt(encrypted_raw.encode()).decode("utf-8")
                    payload = json.loads(decrypted_json)
                except (InvalidToken, json.JSONDecodeError, UnicodeDecodeError):
                    logger.warning(f"Failed to decrypt payload for key {key}. Skipping.")
                    continue

                yield key, payload
        except (redis.RedisError, OSError) as exc:
            logger.warning(f"Failed to scan credential tokens: {exc}")


token_store = TokenStore()
