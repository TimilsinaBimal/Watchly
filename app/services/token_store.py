import base64
import json
from collections.abc import AsyncIterator
from typing import Any

import redis.asyncio as redis
from async_lru import alru_cache
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
        # Negative cache for missing tokens to avoid repeated Redis GETs
        # when external probes request non-existent tokens.
        self._missing_tokens: TTLCache = TTLCache(maxsize=10000, ttl=86400)
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
                "Server misconfiguration: TOKEN_SALT must be set to a non-default value before storing" " credentials."
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
            import traceback

            logger.info("Creating shared Redis client")
            # Limit the number of pooled connections to avoid unbounded growth
            # `max_connections` is forwarded to ConnectionPool.from_url
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
            if getattr(self, "_creation_count", None) is None:
                self._creation_count = 1
            else:
                self._creation_count += 1
                logger.warning(
                    f"Redis client creation invoked again (count={self._creation_count})."
                    f" Stack:\n{''.join(traceback.format_stack())}"
                )
        return self._client

    async def close(self) -> None:
        """Close and disconnect the shared Redis client (call on shutdown)."""
        if self._client is None:
            return
        try:
            logger.info("Closing shared Redis client")
            # Close client and disconnect underlying pool
            try:
                await self._client.close()
            except Exception:
                pass
            try:
                pool = getattr(self._client, "connection_pool", None)
                if pool is not None:
                    # connection_pool.disconnect may be a coroutine in some redis implementations
                    disconnect = getattr(pool, "disconnect", None)
                    if disconnect:
                        res = disconnect()
                        if hasattr(res, "__await__"):
                            await res
            except Exception:
                pass
        finally:
            self._client = None

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

        # Invalidate async LRU cache for fresh reads on subsequent requests
        try:
            # bound method supports targeted invalidation by argument(s)
            self.get_user_data.cache_invalidate(token)
        except KeyError:
            # The token was not in the cache, no action needed.
            pass
        except Exception as e:
            logger.warning(f"Targeted cache invalidation failed: {e}. Falling back to clearing cache.")
            try:
                self.get_user_data.cache_clear()
            except Exception as e_clear:
                logger.error(f"Error while clearing cache: {e_clear}")

        # Ensure we remove from negative cache so new value is read next time
        try:
            if token in self._missing_tokens:
                del self._missing_tokens[token]
        except Exception:
            pass

        return token

    @alru_cache(maxsize=10000, ttl=43200)
    async def get_user_data(self, token: str) -> dict[str, Any] | None:
        # Short-circuit for tokens known to be missing
        try:
            if token in self._missing_tokens:
                logger.debug(f"[REDIS] Negative cache hit for missing token {token}")
                return None
        except Exception:
            pass

        logger.debug(f"[REDIS] Cache miss. Fetching data from redis for {token}")
        key = self._format_key(token)
        client = await self._get_client()
        data_raw = await client.get(key)

        if not data_raw:
            # remember negative result briefly
            try:
                self._missing_tokens[token] = True
            except Exception:
                pass
            return None

        try:
            data = json.loads(data_raw)
            if data.get("authKey"):
                data["authKey"] = self.decrypt_token(data["authKey"])
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

        # Invalidate async LRU cache so future reads reflect deletion
        try:
            if token:
                self.get_user_data.cache_invalidate(token)
            else:
                # If only key is provided, clear cache entirely to be safe
                self.get_user_data.cache_clear()
        except KeyError:
            # The token was not in the cache, no action needed.
            pass
        except Exception as e:
            logger.warning(f"Failed to invalidate user data cache during token deletion: {e}")

        # Remove from negative cache as token is deleted
        try:
            if token and token in self._missing_tokens:
                del self._missing_tokens[token]
        except Exception:
            pass

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
                        # Token payload ready for consumer
                        tok = k[len(self.KEY_PREFIX) :] if k.startswith(self.KEY_PREFIX) else k  # noqa
                        yield k, payload
                    buffer.clear()

            # Flush remainder
            if buffer:
                try:
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
                    yield k, payload
        except (redis.RedisError, OSError) as exc:
            logger.warning(f"Failed to scan credential tokens: {exc}")


token_store = TokenStore()
