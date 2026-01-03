import base64
import json
from typing import Any

import redis.asyncio as redis
from async_lru import alru_cache
from cachetools import TTLCache
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from loguru import logger

from app.core.config import settings
from app.core.security import redact_token
from app.services.redis_service import redis_service
from app.services.user_cache import user_cache


class TokenStore:
    """Redis-backed store for user credentials and auth tokens."""

    KEY_PREFIX = settings.REDIS_TOKEN_KEY

    def __init__(self) -> None:
        # Negative cache for missing tokens to avoid repeated Redis GETs
        # when external probes request non-existent tokens.
        self._missing_tokens: TTLCache = TTLCache(maxsize=10000, ttl=86400)

        if not settings.TOKEN_SALT or settings.TOKEN_SALT == "change-me":
            logger.warning(
                "TOKEN_SALT is missing or using the default placeholder. Set a strong value to secure tokens."
            )

    def _ensure_secure_salt(self) -> None:
        if not settings.TOKEN_SALT or settings.TOKEN_SALT == "change-me":
            logger.error("TOKEN_SALT is unset or using the insecure default.")
            raise RuntimeError("TOKEN_SALT must be set to a non-default value before storing credentials.")

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

        # Securely store password if provided (primary login mode)
        if storage_data.get("password"):
            try:
                storage_data["password"] = self.encrypt_token(storage_data["password"])
            except Exception as exc:
                logger.error(f"Password encryption failed for {redact_token(user_id)}: {exc}")
                # Do not store plaintext passwords
                raise RuntimeError("PASSWORD_ENCRYPT_FAILED")

        # Encrypt poster_rating API key if present
        if storage_data.get("settings") and isinstance(storage_data["settings"], dict):
            poster_rating = storage_data["settings"].get("poster_rating")
            if poster_rating and isinstance(poster_rating, dict) and poster_rating.get("api_key"):
                try:
                    # Only encrypt if it's not already encrypted (check if it's a valid encrypted string)
                    api_key = poster_rating["api_key"]
                    # Simple check: encrypted tokens are base64-like and longer
                    # If it looks like plaintext, encrypt it
                    # Fernet encrypted tokens start with "gAAAAAB"
                    if not api_key.startswith("gAAAAAB"):
                        poster_rating["api_key"] = self.encrypt_token(api_key)
                except Exception as exc:
                    logger.warning(f"Failed to encrypt poster_rating api_key for {redact_token(user_id)}: {exc}")
        json_str = json.dumps(storage_data)

        if settings.TOKEN_TTL_SECONDS and settings.TOKEN_TTL_SECONDS > 0:
            await redis_service.set(key, json_str, settings.TOKEN_TTL_SECONDS)
        else:
            await redis_service.set(key, json_str)

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
        except Exception as e:
            logger.debug(f"Failed to clear negative cache for {token}: {e}")

        return token

    async def update_user_data(self, token: str, payload: dict[str, Any]) -> str:
        """Update user data by token. This is a convenience wrapper around store_user_data."""
        user_id = self.get_user_id_from_token(token)
        return await self.store_user_data(user_id, payload)

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
        # Remove it since we've migrated to poster_rating or it's no longer needed
        if "rpdb_key" in settings_dict:
            settings_dict.pop("rpdb_key")
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

                # Invalidate cache so next read gets the migrated data
                try:
                    self.get_user_data.cache_invalidate(token)
                except Exception:
                    pass

                logger.info(
                    "[MIGRATION] Successfully migrated and encrypted poster_rating " f"format for {redact_token(token)}"
                )
                return data
            except Exception as e:
                logger.warning(f"[MIGRATION] Failed to save migrated data for {redact_token(token)}: {e}")
                return None

        return None

    @alru_cache(maxsize=2000, ttl=43200)
    async def get_user_data(self, token: str) -> dict[str, Any] | None:
        # Short-circuit for tokens known to be missing
        try:
            if token in self._missing_tokens:
                logger.debug(f"[REDIS] Negative cache hit for missing token {token}")
                return None
        except Exception as e:
            logger.debug(f"Failed to check negative cache for {token}: {e}")

        logger.debug(f"[REDIS] Cache miss. Fetching data from redis for {token}")
        key = self._format_key(token)
        data_raw = await redis_service.get(key)

        if not data_raw:
            # remember negative result briefly
            try:
                self._missing_tokens[token] = True
            except Exception as e:
                logger.debug(f"Failed to set negative cache for missing token {token}: {e}")
            return None

        try:
            data = json.loads(data_raw)
        except json.JSONDecodeError:
            return None

        updated_data = await self._migrate_poster_rating_format_raw(token, key, data)
        if updated_data:
            data = updated_data

        # Decrypt fields individually; do not fail entire record on decryption errors
        if data.get("authKey"):
            try:
                data["authKey"] = self.decrypt_token(data["authKey"])
            except Exception as e:
                logger.warning(f"Decryption failed for authKey associated with {redact_token(token)}: {e}")
                # Leave as-is (legacy plaintext or previous failure)
                pass
        if data.get("password"):
            try:
                data["password"] = self.decrypt_token(data["password"])
            except Exception as e:
                logger.warning(f"Decryption failed for password associated with {redact_token(token)}: {e}")
                # require re-login path when needed
                data["password"] = None

        # Decrypt poster_rating API key if present
        if data.get("settings") and isinstance(data["settings"], dict):
            poster_rating = data["settings"].get("poster_rating")
            if poster_rating and isinstance(poster_rating, dict) and poster_rating.get("api_key"):
                try:
                    poster_rating["api_key"] = self.decrypt_token(poster_rating["api_key"])
                except Exception as e:
                    logger.warning(
                        "Decryption failed for poster_rating api_key associated " f"with {redact_token(token)}: {e}"
                    )
                    poster_rating["api_key"] = None

        return data

    async def delete_token(self, token: str = None, key: str = None) -> None:
        if not token and not key:
            raise ValueError("Either token or key must be provided")
        if token:
            key = self._format_key(token)

        await redis_service.delete(key)
        # we also need to delete the cached library items, profiles and watched sets
        if token:
            try:
                await user_cache.invalidate_all_user_data(token)
            except Exception as e:
                logger.warning(f"Failed to invalidate all user data for {redact_token(token)}: {e}")

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
        except Exception as e:
            logger.debug(f"Failed to clear negative cache during deletion: {e}")

    async def count_users(self) -> int:
        """Count total users by scanning Redis keys with the configured prefix.

        Cached for 12 hours to avoid frequent Redis scans.
        """
        try:
            client = await redis_service.get_client()
        except (redis.RedisError, OSError) as exc:
            logger.warning(f"Cannot count users; Redis unavailable: {exc}")
            return 0

        pattern = f"{self.KEY_PREFIX}*"
        total = 0
        try:
            async for _ in client.scan_iter(match=pattern, count=500):
                total += 1
        except (redis.RedisError, OSError) as exc:
            logger.warning(f"Failed to scan for user count: {exc}")
            return 0
        return total


token_store = TokenStore()
