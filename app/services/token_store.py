import base64
import contextvars
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
        # Cache decrypted payloads for 1 day (86400s) to reduce Redis hits
        # Max size 5000 allows many active users without eviction
        self._payload_cache: TTLCache = TTLCache(maxsize=5000, ttl=86400)
        # per-request redis call counter (context-local)
        self._redis_calls_var: contextvars.ContextVar[int] = contextvars.ContextVar("watchly_redis_calls", default=0)

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
        salt = b"x7FDf9kypzQ1LmR32b8hWv49sKq2Pd8T"
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=200_000,
        )

        key = base64.urlsafe_b64encode(kdf.derive(settings.TOKEN_SALT.encode("utf-8")))
        return Fernet(key)

    def encrypt_token(self, token: str) -> str:
        cipher = self._get_cipher()
        return cipher.encrypt(token.encode("utf-8")).decode("utf-8")

    def decrypt_token(self, enc: str) -> str:
        cipher = self._get_cipher()
        return cipher.decrypt(enc.encode("utf-8")).decode("utf-8")

    async def _get_client(self) -> redis.Redis:
        if self._client is None:
            # Add socket timeouts to avoid hanging on Redis operations
            self._client = redis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
                encoding="utf-8",
                socket_connect_timeout=5,
                socket_timeout=5,
            )
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
            self._incr_calls()
            await client.setex(key, settings.TOKEN_TTL_SECONDS, json_str)
        else:
            self._incr_calls()
            await client.set(key, json_str)

        # Update cache with the payload
        self._payload_cache[token] = payload

        return token

    async def get_user_data(self, token: str) -> dict[str, Any] | None:
        if token in self._payload_cache:
            logger.info(f"[REDIS] Using cached redis data {token}")
            return self._payload_cache[token]
        logger.info(f"[REDIS]Caching Failed. Fetching data from redis for {token}")

        key = self._format_key(token)
        client = await self._get_client()
        self._incr_calls()
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
        self._incr_calls()
        await client.delete(key)

        # Invalidate local cache
        if token and token in self._payload_cache:
            del self._payload_cache[token]

    async def iter_payloads(self, batch_size: int = 200) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        try:
            client = await self._get_client()
        except (redis.RedisError, OSError) as exc:
            logger.warning(f"Skipping credential iteration; Redis unavailable: {exc}")
            return

        pattern = f"{self.KEY_PREFIX}*"

        try:
            buffer: list[str] = []
            async for key in client.scan_iter(match=pattern, count=batch_size):
                buffer.append(key)
                if len(buffer) >= batch_size:
                    try:
                        self._incr_calls()
                        values = await client.mget(buffer)
                    except (redis.RedisError, OSError) as exc:
                        logger.warning(f"Failed batch fetch for {len(buffer)} keys: {exc}")
                        values = [None] * len(buffer)
                    for k, data_raw in zip(buffer, values):
                        if not data_raw:
                            continue
                        try:
                            payload = json.loads(data_raw)
                        except json.JSONDecodeError:
                            logger.warning(f"Failed to decode payload for key {redact_token(k)}. Skipping.")
                            continue
                        # Decrypt authKey for downstream consumers
                        try:
                            if payload.get("authKey"):
                                payload["authKey"] = self.decrypt_token(payload["authKey"])
                        except Exception:
                            pass
                        # Update L1 cache (token only)
                        tok = k[len(self.KEY_PREFIX) :] if k.startswith(self.KEY_PREFIX) else k  # noqa
                        self._payload_cache[tok] = payload
                        yield k, payload
                    buffer.clear()

            # Flush remainder
            if buffer:
                try:
                    self._incr_calls()
                    values = await client.mget(buffer)
                except (redis.RedisError, OSError) as exc:
                    logger.warning(f"Failed batch fetch for {len(buffer)} keys: {exc}")
                    values = [None] * len(buffer)
                for k, data_raw in zip(buffer, values):
                    if not data_raw:
                        continue
                    try:
                        payload = json.loads(data_raw)
                    except json.JSONDecodeError:
                        logger.warning(f"Failed to decode payload for key {redact_token(k)}. Skipping.")
                        continue
                    try:
                        if payload.get("authKey"):
                            payload["authKey"] = self.decrypt_token(payload["authKey"])
                    except Exception:
                        pass
                    tok = k[len(self.KEY_PREFIX) :] if k.startswith(self.KEY_PREFIX) else k  # noqa
                    self._payload_cache[tok] = payload
                    yield k, payload
        except (redis.RedisError, OSError) as exc:
            logger.warning(f"Failed to scan credential tokens: {exc}")

    # ---- Diagnostics ----
    def _incr_calls(self) -> None:
        try:
            current = self._redis_calls_var.get()
            self._redis_calls_var.set(current + 1)
        except Exception:
            pass

    def reset_call_counter(self) -> None:
        try:
            self._redis_calls_var.set(0)
        except Exception:
            pass

    def get_call_count(self) -> int:
        try:
            return int(self._redis_calls_var.get())
        except Exception:
            return 0


token_store = TokenStore()
