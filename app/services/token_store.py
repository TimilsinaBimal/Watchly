import base64
import json
from collections.abc import AsyncIterator
from typing import Any

import redis.asyncio as redis
from cachetools import TTLCache
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from loguru import logger

from app.core.config import settings
from app.core.security import redact_token


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
        salt = b"x7FDf9kypzQ1LmR32b8hWv49sKq2Pd8T"
        if self._cipher is None:
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=salt,
                iterations=200_000,
            )

            key = base64.urlsafe_b64encode(kdf.derive(settings.TOKEN_SALT.encode("utf-8")))
            self._cipher = Fernet(key)
        return self._cipher

    def encrypt_token(self, token: str) -> str:
        return self._cipher.encrypt(token.encode("utf-8")).decode("utf-8")

    def decrypt_token(self, enc: str) -> str:
        return self._cipher.decrypt(enc.encode("utf-8")).decode("utf-8")

    async def _get_client(self) -> redis.Redis:
        if self._client is None:
            self._client = redis.from_url(settings.REDIS_URL, decode_responses=True, encoding="utf-8")
        return self._client

    def _format_key(self, token: str) -> str:
        """Format Redis key from token."""
        return f"{self.KEY_PREFIX}{token}"

    def get_token_from_user_id(self, user_id: str) -> str:
        return user_id.strip()

    def get_user_id_from_token(self, token: str) -> str:
        return token.strip() if token else ""

    async def store_user_data(self, user_id: str, payload: dict[str, Any]) -> str:
        self._ensure_secure_salt()
        token = self.get_token_from_user_id(user_id)
        key = self._format_key(token)

        # Prepare data for storage (Plain JSON, no encryption needed)
        storage_data = payload.copy()

        # Store user_id in payload for convenience
        storage_data["user_id"] = user_id

        if storage_data.get("authKey"):
            storage_data["authKey"] = self.encrypt_token(storage_data["authKey"])

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
            if data.get("authKey"):
                data["authKey"] = self.decrypt_token(data["authKey"])
            self._payload_cache[token] = data
            return data
        except (json.JSONDecodeError, InvalidToken):
            return None

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
                    logger.warning(f"Failed to fetch payload for {redact_token(key)}: {exc}")
                    continue

                if not data_raw:
                    continue

                try:
                    payload = json.loads(data_raw)
                except json.JSONDecodeError:
                    logger.warning(f"Failed to decode payload for key {redact_token(key)}. Skipping.")
                    continue

                yield key, payload
        except (redis.RedisError, OSError) as exc:
            logger.warning(f"Failed to scan credential tokens: {exc}")


token_store = TokenStore()
