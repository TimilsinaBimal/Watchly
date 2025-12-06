import base64
import hashlib
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

    def _format_key(self, token: str) -> str:
        """Format Redis key from token."""
        return f"{self.KEY_PREFIX}{token}"

    def _encrypt_password(self, password: str) -> str:
        """Encrypt password using Fernet."""
        if not password:
            return None
        return self._get_cipher().encrypt(password.encode()).decode("utf-8")

    def _decrypt_password(self, encrypted_password: str) -> str:
        """Decrypt password using Fernet."""
        if not encrypted_password:
            return None
        try:
            return self._get_cipher().decrypt(encrypted_password.encode()).decode("utf-8")
        except InvalidToken:
            return None

    def get_token_from_user_id(self, user_id: str) -> str:
        """Generate token from user_id (plain user_id as token)."""
        if not user_id:
            raise ValueError("User ID is required to generate token")
        # Use user_id directly as token (no encryption)
        return user_id.strip()

    def get_user_id_from_token(self, token: str) -> str:
        """Get user_id from token (they are the same now)."""
        return token.strip() if token else ""

    async def store_user_data(self, user_id: str, payload: dict[str, Any]) -> str:
        self._ensure_secure_salt()

        token = self.get_token_from_user_id(user_id)
        key = self._format_key(token)

        # Prepare data for storage (Plain JSON, no password encryption needed)
        storage_data = payload.copy()

        # Store user_id in payload for convenience
        storage_data["user_id"] = user_id

        client = await self._get_client()
        json_str = json.dumps(storage_data)

        if settings.TOKEN_TTL_SECONDS and settings.TOKEN_TTL_SECONDS > 0:
            await client.setex(key, settings.TOKEN_TTL_SECONDS, json_str)
        else:
            await client.set(key, json_str)

        # Update cache with the payload
        self._payload_cache[token] = payload

        return token

    async def get_user_data(self, token: str) -> dict[str, Any] | None:
        if token in self._payload_cache:
            return self._payload_cache[token]

        key = self._format_key(token)
        client = await self._get_client()
        data_raw = await client.get(key)

        if not data_raw:
            return None

        try:
            data = json.loads(data_raw)
            self._payload_cache[token] = data
            return data
        except json.JSONDecodeError:
            return None

    # Alias for compatibility with existing calls, but implementation changed
    def derive_token(self, payload: dict[str, Any]) -> str:
        # We can't really derive token from mixed payload anymore unless we have email.
        # This might break existing calls in `tokens.py`. We need to fix `tokens.py` to use `get_token_from_email`.
        raise NotImplementedError("Use get_token_from_email instead")

    async def get_payload(self, token: str) -> dict[str, Any] | None:
        return await self.get_user_data(token)

    async def store_payload(self, payload: dict[str, Any]) -> tuple[str, bool]:
        # This signature doesn't match new logic which needs email explicitly or inside payload.
        # We will update tokens.py first.
        raise NotImplementedError("Use store_user_data instead")

    async def delete_token(self, token: str = None, key: str = None) -> None:
        if not token and not key:
            raise ValueError("Either token or key must be provided")
        if token:
            key = self._format_key(token)

        client = await self._get_client()
        await client.delete(key)

        # Invalidate local cache
        if token and token in self._payload_cache:
            del self._payload_cache[token]

    async def iter_payloads(self) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """Iterate over all stored payloads, yielding key and payload."""
        try:
            client = await self._get_client()
        except (redis.RedisError, OSError) as exc:
            logger.warning(f"Skipping credential iteration; Redis unavailable: {exc}")
            return

        pattern = f"{self.KEY_PREFIX}*"

        try:
            async for key in client.scan_iter(match=pattern):
                try:
                    data_raw = await client.get(key)
                except (redis.RedisError, OSError) as exc:
                    logger.warning(f"Failed to fetch payload for {key}: {exc}")
                    continue

                if not data_raw:
                    continue

                try:
                    payload = json.loads(data_raw)
                except json.JSONDecodeError:
                    logger.warning(f"Failed to decode payload for key {key}. Skipping.")
                    continue

                yield key, payload
        except (redis.RedisError, OSError) as exc:
            logger.warning(f"Failed to scan credential tokens: {exc}")


token_store = TokenStore()
