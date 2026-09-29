import base64
import copy
import json
import secrets
from functools import lru_cache
from typing import Any

import redis.asyncio as redis
from async_lru import alru_cache
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from loguru import logger

from app.core.config import settings
from app.core.constants import IDENTITY_KEY, TOKEN_ALIAS_KEY
from app.core.security import _SECRET_NESTED_FIELDS, _SECRET_SETTINGS_FIELDS, redact_token
from app.services.redis_service import redis_service
from app.services.user_cache import user_cache

# Every Fernet token starts with this (version byte 0x80, base64).
FERNET_PREFIX = "gAAAAA"


# Keyed on the salt so a changed TOKEN_SALT (tests patch it) derives a new key; the
# 200k-iteration PBKDF2 is ~55 ms of blocking CPU, so it runs once per salt.
@lru_cache(maxsize=1)
def _cipher_for(token_salt: str) -> Fernet:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"x7FDf9kypzQ1LmR32b8hWv49sKq2Pd8T",
        iterations=200_000,
    )
    return Fernet(base64.urlsafe_b64encode(kdf.derive(token_salt.encode("utf-8"))))


class TokenStore:
    """Redis-backed store for user credentials and auth tokens."""

    KEY_PREFIX = settings.REDIS_TOKEN_KEY

    def __init__(self) -> None:
        if not settings.TOKEN_SALT or settings.TOKEN_SALT == "change-me":
            logger.warning(
                "TOKEN_SALT is missing or using the default placeholder. Set a strong value to secure tokens."
            )

    def _ensure_secure_salt(self) -> None:
        if not settings.TOKEN_SALT or settings.TOKEN_SALT == "change-me":
            logger.error("TOKEN_SALT is unset or using the insecure default.")
            raise RuntimeError("TOKEN_SALT must be set to a non-default value before storing credentials.")

    def encrypt_token(self, token: str) -> str:
        return _cipher_for(settings.TOKEN_SALT).encrypt(token.encode("utf-8")).decode("utf-8")

    def decrypt_token(self, enc: str) -> str:
        return _cipher_for(settings.TOKEN_SALT).decrypt(enc.encode("utf-8")).decode("utf-8")

    def _encrypt_once(self, value: str) -> str:
        return value if value.startswith(FERNET_PREFIX) else self.encrypt_token(value)

    def _decrypt_if_encrypted(self, token: str, field: str, value: str) -> str | None:
        if not value.startswith(FERNET_PREFIX):
            return value
        try:
            return self.decrypt_token(value)
        except InvalidToken:
            logger.warning(f"[{redact_token(token)}] {field} did not decrypt; dropping it")
            return None

    def _format_key(self, token: str) -> str:
        return f"{self.KEY_PREFIX}{token}"

    @staticmethod
    def mint_token() -> str:
        """Generate an opaque account token for the manifest URL."""
        return secrets.token_urlsafe(16)

    def _identity_key(self, provider: str, provider_user_id: str) -> str:
        return IDENTITY_KEY.format(provider=provider, provider_user_id=provider_user_id)

    async def _set_with_token_ttl(self, key: str, value: str) -> None:
        if settings.TOKEN_TTL_SECONDS and settings.TOKEN_TTL_SECONDS > 0:
            await redis_service.set(key, value, settings.TOKEN_TTL_SECONDS)
        else:
            await redis_service.set(key, value)

    async def get_token_for_identity(self, provider: str, provider_user_id: str) -> str | None:
        token = await redis_service.get(self._identity_key(provider, provider_user_id))
        return await self.resolve_alias(token) if token else None

    async def set_identity(self, provider: str, provider_user_id: str, token: str) -> None:
        await self._set_with_token_ttl(self._identity_key(provider, provider_user_id), token)

    async def delete_identity(self, provider: str, provider_user_id: str) -> None:
        await redis_service.delete(self._identity_key(provider, provider_user_id))

    async def resolve_alias(self, token: str) -> str:
        """Follow merge aliases to the surviving account token.

        Bounded walk: chains only grow when an already-merged account is merged
        again, so they stay short.
        """
        for _ in range(5):
            target = await redis_service.get(TOKEN_ALIAS_KEY.format(token=token))
            if not target:
                break
            token = target
        return token

    async def merge_into(self, absorbed_token: str, surviving_token: str) -> None:
        """Merge an account into another, keeping the absorbed manifest URL working.

        The alias is written before the absorbed record is deleted so concurrent
        requests never hit a window where neither resolves. Identity index
        entries still pointing at the absorbed token resolve through the alias.
        """
        await self._set_with_token_ttl(TOKEN_ALIAS_KEY.format(token=absorbed_token), surviving_token)
        await self.delete_token(absorbed_token)

    async def store_user_data(self, token: str, payload: dict[str, Any]) -> str:
        self._ensure_secure_salt()
        key = self._format_key(token)

        # Deep: the settings dict below is encrypted in place, and callers often pass
        # the shared dict get_user_data returned.
        storage_data = copy.deepcopy(payload)

        if storage_data.get("authKey"):
            storage_data["authKey"] = self.encrypt_token(storage_data["authKey"])
        if storage_data.get("password"):
            storage_data["password"] = self.encrypt_token(storage_data["password"])

        user_settings = storage_data.get("settings") or {}
        for field in _SECRET_SETTINGS_FIELDS:
            if user_settings.get(field):
                user_settings[field] = self._encrypt_once(user_settings[field])
        for field in _SECRET_NESTED_FIELDS:
            block = user_settings.get(field)
            if block and block.get("api_key"):
                block["api_key"] = self._encrypt_once(block["api_key"])

        json_str = json.dumps(storage_data)

        if settings.TOKEN_TTL_SECONDS and settings.TOKEN_TTL_SECONDS > 0:
            await redis_service.set(key, json_str, settings.TOKEN_TTL_SECONDS)
        else:
            await redis_service.set(key, json_str)

        # Settings changes alter the catalog list, so a cached manifest built from
        # the old settings must not survive the write.
        await user_cache.invalidate_manifest(token)
        self._get_user_data_cached.cache_invalidate(token)

        return token

    async def update_user_data(self, token: str, payload: dict[str, Any]) -> str:
        """Update user data by token. This is a convenience wrapper around store_user_data.

        Resolves merge aliases first so writes through an absorbed token land on
        the surviving account instead of resurrecting the absorbed one.
        """
        token = await self.resolve_alias(token)
        return await self.store_user_data(token, payload)

    async def _migrate_poster_rating_format_raw(self, token: str, redis_key: str, data: dict) -> dict | None:
        """Migrate old rpdb_key format to new poster_rating format in raw Redis data if needed."""
        if not data:
            return None

        settings_dict = data.get("settings")
        if not settings_dict or not isinstance(settings_dict, dict):
            return None

        rpdb_key = settings_dict.get("rpdb_key")
        poster_rating = settings_dict.get("poster_rating")
        needs_save = False

        # Case 1: Migrate rpdb_key to poster_rating if rpdb_key exists and poster_rating doesn't
        if rpdb_key and not poster_rating:
            logger.info(f"[MIGRATION] Migrating rpdb_key to poster_rating format for {redact_token(token)}")
            settings_dict["poster_rating"] = {
                "provider": "rpdb",
                "api_key": self.encrypt_token(rpdb_key),  # Encrypt the API key
            }
            needs_save = True

        # Case 2: Clean up deprecated rpdb_key field if it exists (even if empty/null)
        # Remove it since we've migrated to poster_rating or it's no longer needed.
        # Do not overwrite a valid migrated poster_rating payload.
        if "rpdb_key" in settings_dict:
            settings_dict.pop("rpdb_key")
            if not settings_dict.get("poster_rating"):
                settings_dict["poster_rating"] = {
                    "provider": "rpdb",
                    "api_key": None,
                }
            if not needs_save:  # Only log if we didn't already log migration
                logger.info(f"[MIGRATION] Removing deprecated rpdb_key field for {redact_token(token)}")
            needs_save = True

        # Save back to redis if any changes were made
        if needs_save:
            try:
                if settings.TOKEN_TTL_SECONDS and settings.TOKEN_TTL_SECONDS > 0:
                    await redis_service.set(redis_key, json.dumps(data), settings.TOKEN_TTL_SECONDS)
                else:
                    await redis_service.set(redis_key, json.dumps(data))

                self._get_user_data_cached.cache_invalidate(token)

                logger.info(
                    "[MIGRATION] Successfully migrated and encrypted poster_rating " f"format for {redact_token(token)}"
                )
                return data
            except Exception as e:
                logger.warning(f"[MIGRATION] Failed to save migrated data for {redact_token(token)}: {e}")
                return None

        return None

    async def get_user_data(self, token: str) -> dict[str, Any] | None:
        data = await self._get_user_data_cached(token)
        if data is None:
            # Don't let a missing-token result get pinned in the per-process cache;
            # otherwise a token created on another worker would 401 here for hours.
            self._get_user_data_cached.cache_invalidate(token)
        return data

    # 5-minute TTL: keeps reads cheap under bursty traffic but bounds the window
    # in which a deleted token can keep authenticating on a worker that didn't
    # observe the local cache invalidation (e.g. multi-worker deployments).
    @alru_cache(maxsize=2000, ttl=300)
    async def _get_user_data_cached(self, token: str) -> dict[str, Any] | None:
        logger.debug(f"[{redact_token(token)}] User data cache miss")
        key = self._format_key(token)
        data_raw = await redis_service.get(key)

        if not data_raw:
            return None

        try:
            data = json.loads(data_raw)
        except json.JSONDecodeError:
            return None

        updated_data = await self._migrate_poster_rating_format_raw(token, key, data)
        if updated_data:
            data = updated_data

        # Decrypt fields individually; do not fail the entire record on one bad field.
        if data.get("authKey"):
            try:
                data["authKey"] = self.decrypt_token(data["authKey"])
            except InvalidToken:
                # Legacy plaintext authKey from before encryption.
                logger.warning(f"[{redact_token(token)}] authKey did not decrypt; using it as stored")
        if data.get("password"):
            try:
                data["password"] = self.decrypt_token(data["password"])
            except InvalidToken:
                logger.warning(f"[{redact_token(token)}] password did not decrypt; a re-login is needed")
                data["password"] = None

        user_settings = data.get("settings") or {}
        for field in _SECRET_SETTINGS_FIELDS:
            if user_settings.get(field):
                user_settings[field] = self._decrypt_if_encrypted(token, field, user_settings[field])
        for field in _SECRET_NESTED_FIELDS:
            block = user_settings.get(field)
            if block and block.get("api_key"):
                block["api_key"] = self._decrypt_if_encrypted(token, f"{field}.api_key", block["api_key"])

        return data

    async def delete_token(self, token: str) -> None:
        await redis_service.delete(self._format_key(token))
        await user_cache.invalidate_all_user_data(token)
        self._get_user_data_cached.cache_invalidate(token)

    # The configure page shows this on every load, and a SCAN walks the whole
    # keyspace. Per process is fine: it's a display number. token_store is a
    # process singleton, so caching the method doesn't retain per-request state.
    @alru_cache(maxsize=1, ttl=43200)
    async def count_users(self) -> int:
        try:
            client = await redis_service.get_client()
            return sum([1 async for _ in client.scan_iter(match=f"{self.KEY_PREFIX}*", count=500)])
        except (redis.RedisError, OSError) as exc:
            logger.warning(f"Cannot count users; Redis unavailable: {exc}")
            return 0


token_store = TokenStore()
