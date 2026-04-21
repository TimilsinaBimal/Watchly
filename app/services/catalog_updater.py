import asyncio
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from loguru import logger

from app.core.config import settings
from app.core.security import redact_token
from app.services.auth import auth_service
from app.services.stremio.service import StremioBundle
from app.services.token_store import token_store


class CatalogUpdater:
    """
    Triggers on-demand catalog updates by building a fresh manifest
    and pushing the catalogs to Stremio's addon collection.
    Uses in-memory locking to prevent duplicate concurrent updates.
    """

    def __init__(self):
        self._updating_tokens: set[str] = set()

    def _needs_update(self, credentials: dict[str, Any]) -> bool:
        """Check if catalog update is needed based on last_updated timestamp."""
        if not credentials:
            return False

        last_updated = credentials.get("last_updated")
        if not last_updated:
            return True

        try:
            if isinstance(last_updated, str):
                last_update_time = datetime.fromisoformat(last_updated.replace("Z", "+00:00"))
            else:
                last_update_time = last_updated

            now = datetime.now(timezone.utc)
            if last_update_time.tzinfo is None:
                last_update_time = last_update_time.replace(tzinfo=timezone.utc)

            time_since_update = (now - last_update_time).total_seconds()
            return time_since_update >= (settings.CATALOG_REFRESH_INTERVAL_SECONDS - 3600)
        except (ValueError, TypeError, AttributeError) as e:
            logger.warning(f"Failed to parse last_updated timestamp: {e}. Treating as needs update.")
            return True

    async def refresh_catalogs_for_credentials(
        self, token: str, credentials: dict[str, Any], update_timestamp: bool = True
    ) -> bool:
        """Build a fresh manifest and push the catalogs to Stremio."""
        if not credentials:
            logger.warning(f"[{redact_token(token)}] Attempted to refresh catalogs with no credentials.")
            raise HTTPException(
                status_code=401,
                detail="Invalid or expired token. Please reconfigure the addon.",
            )

        bundle = StremioBundle()
        try:
            auth_key = await auth_service.resolve_auth_key_with_bundle(bundle, credentials, token)
            if not auth_key:
                return True

            # Check if addon is still installed
            try:
                if not await bundle.addons.is_addon_installed(auth_key):
                    logger.info(f"[{redact_token(token)}] Addon not installed, skipping update")
                    return True
            except Exception as e:
                logger.exception(f"[{redact_token(token)}] Failed to check addon install status: {e}")
                return False

            # Reuse ManifestService to build catalogs
            # (handles library caching, profile building, catalog definitions,
            #  translation, and sorting — no need to reimplement here)
            from app.services.manifest import manifest_service

            manifest = await manifest_service.get_manifest_for_token(token)
            catalogs = manifest.get("catalogs", [])

            success = await bundle.addons.update_catalogs(auth_key, catalogs)

            if success and update_timestamp:
                try:
                    now = datetime.now(timezone.utc)
                    credentials["last_updated"] = now.replace(microsecond=0).isoformat()
                    await token_store.update_user_data(token, credentials)
                    logger.debug(f"[{redact_token(token)}] Updated last_updated timestamp")
                except Exception as e:
                    logger.warning(f"[{redact_token(token)}] Failed to update timestamp: {e}")

            return success

        except Exception as e:
            logger.exception(f"[{redact_token(token)}] Failed to update catalogs in background: {e}")
            try:
                error_auth_key = credentials.get("authKey")
                if isinstance(error_auth_key, str) and error_auth_key:
                    description = (
                        "Movie and series recommendations based on your Stremio library.\n\n"
                        f"⚠️ Status: Error\nFailed to update catalogs: {e}"
                    )
                    await bundle.addons.update_description(error_auth_key, description)
            except Exception as update_err:
                logger.warning(f"[{redact_token(token)}] Failed to update addon description: {update_err}")
            return False
        finally:
            await bundle.close()

    async def trigger_update(self, token: str, credentials: dict[str, Any]) -> None:
        """Fire a background catalog update if needed. In-memory lock prevents duplicates."""
        if token in self._updating_tokens:
            logger.debug(f"[{redact_token(token)}] Update already in progress, skipping")
            return

        if not self._needs_update(credentials):
            logger.debug(f"[{redact_token(token)}] Catalog update not needed yet")
            return

        self._updating_tokens.add(token)
        logger.info(f"[{redact_token(token)}] Triggering catalog update")
        asyncio.create_task(self._update_task(token, credentials))

    async def _update_task(self, token: str, credentials: dict[str, Any]) -> None:
        """Background task that performs the actual catalog update."""
        try:
            success = await self.refresh_catalogs_for_credentials(token, credentials, update_timestamp=True)
            if success:
                logger.info(f"[{redact_token(token)}] Catalog update completed successfully")
            else:
                logger.warning(f"[{redact_token(token)}] Catalog update completed with failure")
        except Exception as e:
            logger.exception(f"[{redact_token(token)}] Catalog update task failed: {e}")
        finally:
            self._updating_tokens.discard(token)


logger.info(f"Catalog updater initialized with refresh interval of {settings.CATALOG_REFRESH_INTERVAL_SECONDS} seconds")
catalog_updater = CatalogUpdater()
