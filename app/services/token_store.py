import base64
import json
import secrets
from typing import Any

import redis.asyncio as redis
from async_lru import alru_cache
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
    # provider identity (stremio user id / trakt slug / simkl account id) -> account token
    IDENTITY_KEY_PREFIX = "watchly:identity:"
    # absorbed account token -> surviving account token (written on account merge)
    ALIAS_KEY_PREFIX = "watchly:token_alias:"

    def __init__(self) -> None:
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

    @staticmethod
    def mint_token() -> str:
        """Generate an opaque account token for the manifest URL."""
        return secrets.token_urlsafe(16)

    def _identity_key(self, provider: str, provider_user_id: str) -> str:
        return f"{self.IDENTITY_KEY_PREFIX}{provider}:{provider_user_id}"

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
            target = await redis_service.get(f"{self.ALIAS_KEY_PREFIX}{token}")
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
        await self._set_with_token_ttl(f"{self.ALIAS_KEY_PREFIX}{absorbed_token}", surviving_token)
        await self.delete_token(absorbed_token)

    async def store_user_data(self, token: str, payload: dict[str, Any]) -> str:
        self._ensure_secure_salt()
        key = self._format_key(token)

        # Prepare data for storage (Plain JSON, no encryption needed)
        storage_data = payload.copy()

        if storage_data.get("authKey"):
            storage_data["authKey"] = self.encrypt_token(storage_data["authKey"])

        # Securely store password if provided (primary login mode)
        if storage_data.get("password"):
            try:
                storage_data["password"] = self.encrypt_token(storage_data["password"])
            except Exception as exc:
                logger.error(f"Password encryption failed for {redact_token(token)}: {exc}")
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
                    logger.warning(f"Failed to encrypt poster_rating api_key for {redact_token(token)}: {exc}")

        # Encrypt llm api_key if present
        if storage_data.get("settings") and isinstance(storage_data["settings"], dict):
            llm_config = storage_data["settings"].get("llm")
            if llm_config and isinstance(llm_config, dict) and llm_config.get("api_key"):
                try:
                    if not llm_config["api_key"].startswith("gAAAAAB"):
                        llm_config["api_key"] = self.encrypt_token(llm_config["api_key"])
                except Exception as exc:
                    logger.warning(f"Failed to encrypt llm api_key for {redact_token(token)}: {exc}")

        # Encrypt simkl_api_key if present
        if storage_data.get("settings") and isinstance(storage_data["settings"], dict):
            simkl_api_key = storage_data["settings"].get("simkl_api_key")
            if simkl_api_key:
                try:
                    if not simkl_api_key.startswith("gAAAAAB"):
                        storage_data["settings"]["simkl_api_key"] = self.encrypt_token(simkl_api_key)
                except Exception as exc:
                    logger.warning(f"Failed to encrypt simkl_api_key for {redact_token(token)}: {exc}")

        # Encrypt gemini_api_key if present
        if storage_data.get("settings") and isinstance(storage_data["settings"], dict):
            gemini_api_key = storage_data["settings"].get("gemini_api_key")
            if gemini_api_key:
                try:
                    if not gemini_api_key.startswith("gAAAAAB"):
                        storage_data["settings"]["gemini_api_key"] = self.encrypt_token(gemini_api_key)
                except Exception as exc:
                    logger.warning(f"Failed to encrypt gemini_api_key for {redact_token(token)}: {exc}")

        # Encrypt tmdb_api_key if present
        if storage_data.get("settings") and isinstance(storage_data["settings"], dict):
            tmdb_api_key = storage_data["settings"].get("tmdb_api_key")
            if tmdb_api_key:
                try:
                    if not tmdb_api_key.startswith("gAAAAAB"):
                        storage_data["settings"]["tmdb_api_key"] = self.encrypt_token(tmdb_api_key)
                except Exception as exc:
                    logger.warning(f"Failed to encrypt tmdb_api_key for {redact_token(token)}: {exc}")

        # Encrypt trakt tokens if present
        if storage_data.get("settings") and isinstance(storage_data["settings"], dict):
            for trakt_field in ("trakt_access_token", "trakt_refresh_token"):
                value = storage_data["settings"].get(trakt_field)
                if value:
                    try:
                        if not value.startswith("gAAAAAB"):
                            storage_data["settings"][trakt_field] = self.encrypt_token(value)
                    except Exception as exc:
                        logger.warning(f"Failed to encrypt {trakt_field} for {redact_token(token)}: {exc}")

        # Encrypt simkl_access_token if present
        if storage_data.get("settings") and isinstance(storage_data["settings"], dict):
            simkl_access_token = storage_data["settings"].get("simkl_access_token")
            if simkl_access_token:
                try:
                    if not simkl_access_token.startswith("gAAAAAB"):
                        storage_data["settings"]["simkl_access_token"] = self.encrypt_token(simkl_access_token)
                except Exception as exc:
                    logger.warning(f"Failed to encrypt simkl_access_token for {redact_token(token)}: {exc}")

        json_str = json.dumps(storage_data)

        if settings.TOKEN_TTL_SECONDS and settings.TOKEN_TTL_SECONDS > 0:
            await redis_service.set(key, json_str, settings.TOKEN_TTL_SECONDS)
        else:
            await redis_service.set(key, json_str)

        # Settings changes alter the catalog list, so a cached manifest built from
        # the old settings must not survive the write.
        try:
            await user_cache.invalidate_manifest(token)
        except Exception as e:
            logger.warning(f"Failed to invalidate manifest for {redact_token(token)}: {e}")

        # Invalidate async LRU cache for fresh reads on subsequent requests
        try:
            self._get_user_data_cached.cache_invalidate(token)
        except KeyError:
            pass
        except Exception as e:
            logger.warning(f"Targeted cache invalidation failed: {e}. Falling back to clearing cache.")
            try:
                self._get_user_data_cached.cache_clear()
            except Exception as e_clear:
                logger.error(f"Error while clearing cache: {e_clear}")

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

                # Invalidate cache so next read gets the migrated data
                try:
                    self._get_user_data_cached.cache_invalidate(token)
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

    async def get_user_data(self, token: str) -> dict[str, Any] | None:
        data = await self._get_user_data_cached(token)
        if data is None:
            # Don't let a missing-token result get pinned in the per-process cache;
            # otherwise a token created on another worker would 401 here for hours.
            try:
                self._get_user_data_cached.cache_invalidate(token)
            except Exception:
                pass
        return data

    # 5-minute TTL: keeps reads cheap under bursty traffic but bounds the window
    # in which a deleted token can keep authenticating on a worker that didn't
    # observe the local cache invalidation (e.g. multi-worker deployments).
    @alru_cache(maxsize=2000, ttl=300)
    async def _get_user_data_cached(self, token: str) -> dict[str, Any] | None:
        logger.debug(f"[REDIS] Cache miss. Fetching data from redis for {token}")
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
                    if poster_rating["api_key"].startswith("gAAAAA"):
                        poster_rating["api_key"] = self.decrypt_token(poster_rating["api_key"])
                except Exception as e:
                    logger.debug(
                        f"Decryption failed for poster_rating api_key associated with {redact_token(token)}: {e}"
                    )

            llm_config = data["settings"].get("llm")
            if llm_config and isinstance(llm_config, dict) and llm_config.get("api_key"):
                try:
                    if llm_config["api_key"].startswith("gAAAAA"):
                        llm_config["api_key"] = self.decrypt_token(llm_config["api_key"])
                except Exception as e:
                    logger.debug(f"Decryption failed for llm api_key associated with {redact_token(token)}: {e}")

            simkl_api_key = data["settings"].get("simkl_api_key")
            if simkl_api_key:
                try:
                    if simkl_api_key.startswith("gAAAAA"):
                        data["settings"]["simkl_api_key"] = self.decrypt_token(simkl_api_key)
                except Exception as e:
                    logger.debug(f"Decryption failed for simkl_api_key associated with {redact_token(token)}: {e}")

            gemini_api_key = data["settings"].get("gemini_api_key")
            if gemini_api_key:
                try:
                    if gemini_api_key.startswith("gAAAAA"):
                        data["settings"]["gemini_api_key"] = self.decrypt_token(gemini_api_key)
                except Exception as e:
                    logger.debug(f"Decryption failed for gemini_api_key associated with {redact_token(token)}: {e}")

            tmdb_api_key = data["settings"].get("tmdb_api_key")
            if tmdb_api_key:
                try:
                    if tmdb_api_key.startswith("gAAAAA"):
                        data["settings"]["tmdb_api_key"] = self.decrypt_token(tmdb_api_key)
                except Exception as e:
                    logger.debug(f"Decryption failed for tmdb_api_key associated with {redact_token(token)}: {e}")

            # Decrypt trakt tokens
            for trakt_field in ("trakt_access_token", "trakt_refresh_token"):
                value = data["settings"].get(trakt_field)
                if value:
                    try:
                        if value.startswith("gAAAAA"):
                            data["settings"][trakt_field] = self.decrypt_token(value)
                    except Exception as e:
                        logger.debug(f"Decryption failed for {trakt_field} associated with {redact_token(token)}: {e}")

            # Decrypt simkl_access_token
            simkl_access_token = data["settings"].get("simkl_access_token")
            if simkl_access_token:
                try:
                    if simkl_access_token.startswith("gAAAAA"):
                        data["settings"]["simkl_access_token"] = self.decrypt_token(simkl_access_token)
                except Exception as e:
                    logger.debug(f"Decryption failed for simkl_access_token associated with {redact_token(token)}: {e}")

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
                self._get_user_data_cached.cache_invalidate(token)
            else:
                # If only key is provided, clear cache entirely to be safe
                self._get_user_data_cached.cache_clear()
        except KeyError:
            pass
        except Exception as e:
            logger.warning(f"Failed to invalidate user data cache during token deletion: {e}")

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
