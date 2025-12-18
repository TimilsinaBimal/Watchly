import base64
import json
from collections.abc import AsyncIterator
from typing import Any

import redis.asyncio as redis
from async_lru import alru_cache
from cachetools import TTLCache
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from loguru import logger

from app.core.cache import cache  # Import shared cache
from app.core.config import settings


class TokenStore:
    """Redis-backed store for user credentials and auth tokens."""

    KEY_PREFIX = settings.REDIS_TOKEN_KEY

    def __init__(self) -> None:
        self._missing_tokens: TTLCache = TTLCache(maxsize=10000, ttl=86400)
        self._ensure_secure_salt()

    def _ensure_secure_salt(self) -> None:
        if not settings.TOKEN_SALT or settings.TOKEN_SALT == "change-me":
            logger.warning("TOKEN_SALT insecure or missing.")

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
        return self._get_cipher().encrypt(token.encode("utf-8")).decode("utf-8")

    def decrypt_token(self, enc: str) -> str:
        return self._get_cipher().decrypt(enc.encode("utf-8")).decode("utf-8")

    def is_token_known_missing(self, token: str) -> bool:
        return token in self._missing_tokens

    async def close(self) -> None:
        # No-op as pool is managed by RedisCache now, or we can close generic cache
        pass

    def _format_key(self, token: str) -> str:
        return f"{self.KEY_PREFIX}{token}"

    def get_token_from_user_id(self, user_id: str) -> str:
        return user_id.strip()

    def get_user_id_from_token(self, token: str) -> str:
        return token.strip() if token else ""

    async def store_user_data(self, user_id: str, payload: dict[str, Any]) -> str:
        token = self.get_token_from_user_id(user_id)
        key = self._format_key(token)
        storage_data = payload.copy()
        storage_data["user_id"] = user_id

        if storage_data.get("authKey"):
            storage_data["authKey"] = self.encrypt_token(storage_data["authKey"])
        if storage_data.get("password"):
            storage_data["password"] = self.encrypt_token(storage_data["password"])

        client = await cache.get_client()
        json_str = json.dumps(storage_data)

        if settings.TOKEN_TTL_SECONDS and settings.TOKEN_TTL_SECONDS > 0:
            await client.setex(key, settings.TOKEN_TTL_SECONDS, json_str)
        else:
            await client.set(key, json_str)

        try:
            self.get_user_data.cache_invalidate(token)
            if token in self._missing_tokens:
                del self._missing_tokens[token]
        except Exception:
            pass

        return token

    @alru_cache(maxsize=2000, ttl=43200)
    async def get_user_data(self, token: str) -> dict[str, Any] | None:
        if token in self._missing_tokens:
            return None

        key = self._format_key(token)
        data_raw = await cache.get(key)

        if not data_raw:
            self._missing_tokens[token] = True
            return None
        try:
            data = json.loads(data_raw)
            if data.get("authKey"):
                data["authKey"] = self.decrypt_token(data["authKey"])
            if data.get("password"):
                data["password"] = self.decrypt_token(data["password"])
            return data
        except Exception as e:
            logger.error(f"Error reading/decrypting token data: {e}")
            return None

    async def delete_token(self, token: str = None, key: str = None) -> None:
        if token:
            key = self._format_key(token)
        await cache.delete(key)
        try:
            if token:
                self.get_user_data.cache_invalidate(token)
                if token in self._missing_tokens:
                    del self._missing_tokens[token]
        except Exception:
            pass

    async def iter_payloads(self, batch_size: int = 200) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        try:
            client = await cache.get_client()
        except Exception:
            return

        pattern = f"{self.KEY_PREFIX}*"
        try:
            buffer = []
            async for key in client.scan_iter(match=pattern, count=batch_size):
                buffer.append(key)
                if len(buffer) >= batch_size:
                    values = await client.mget(buffer)
                    for k, raw in zip(buffer, values):
                        if not raw:
                            continue
                        try:
                            pl = json.loads(raw)
                            if pl.get("authKey"):
                                pl["authKey"] = self.decrypt_token(pl["authKey"])
                            yield k, pl
                        except Exception:
                            pass
                    buffer.clear()
            if buffer:
                values = await client.mget(buffer)
                for k, raw in zip(buffer, values):
                    if not raw:
                        continue
                    try:
                        pl = json.loads(raw)
                        if pl.get("authKey"):
                            pl["authKey"] = self.decrypt_token(pl["authKey"])
                        yield k, pl
                    except Exception:
                        pass
        except Exception as e:
            logger.error(f"Scan failed: {e}")

    async def count_users(self) -> int:
        try:
            client = await cache.get_client()
            total = 0
            async for _ in client.scan_iter(match=f"{self.KEY_PREFIX}*", count=500):
                total += 1
            return total
        except Exception:
            return 0

    async def get_client(self) -> redis.Redis:
        # Proxy to the shared cache client
        return await cache.get_client()


token_store = TokenStore()
