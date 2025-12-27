import asyncio
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from loguru import logger

from app.core.config import settings
from app.core.security import redact_token
from app.core.settings import UserSettings
from app.services.catalog import DynamicCatalogService
from app.services.stremio.service import StremioBundle
from app.services.token_store import token_store
from app.services.translation import translation_service


def get_config_id(catalog) -> str | None:
    catalog_id = catalog.get("id", "")
    if catalog_id.startswith("watchly.theme."):
        return "watchly.theme"
    if catalog_id.startswith("watchly.loved."):
        return "watchly.loved"
    if catalog_id.startswith("watchly.watched."):
        return "watchly.watched"
    return catalog_id


class CatalogUpdater:
    """
    Catalog updater that triggers updates on-demand when users request catalogs.
    Uses in-memory locking to prevent duplicate concurrent updates.
    """

    def __init__(self):
        # In-memory lock to prevent duplicate updates for the same token
        self._updating_tokens: set[str] = set()

    def _needs_update(self, credentials: dict[str, Any]) -> bool:
        """Check if catalog update is needed based on last_updated timestamp."""
        if not credentials:
            return False

        last_updated = credentials.get("last_updated")
        if not last_updated:
            # No timestamp means never updated, needs update
            return True

        try:
            # Parse ISO format timestamp
            if isinstance(last_updated, str):
                last_update_time = datetime.fromisoformat(last_updated.replace("Z", "+00:00"))
            else:
                last_update_time = last_updated

            # Check if more than 11 hours have passed (update if less than 1 hour remaining)
            now = datetime.now(timezone.utc)
            if last_update_time.tzinfo is None:
                last_update_time = last_update_time.replace(tzinfo=timezone.utc)

            time_since_update = (now - last_update_time).total_seconds()
            # Update if less than 1 hour remaining until next update
            return time_since_update >= (settings.CATALOG_REFRESH_INTERVAL_SECONDS - 3600)
        except (ValueError, TypeError, AttributeError) as e:
            logger.warning(f"Failed to parse last_updated timestamp: {e}. Treating as needs update.")
            return True

    async def refresh_catalogs_for_credentials(
        self, token: str, credentials: dict[str, Any], update_timestamp: bool = True
    ) -> bool:
        """
        Refresh catalogs for a user's credentials.

        Args:
            token: User token
            credentials: User credentials dict
            update_timestamp: Whether to update last_updated timestamp on success

        Returns:
            True if update was successful, False otherwise
        """
        if not credentials:
            logger.warning(f"[{redact_token(token)}] Attempted to refresh catalogs with no credentials.")
            raise HTTPException(status_code=401, detail="Invalid or expired token. Please reconfigure the addon.")

        auth_key = credentials.get("authKey")
        # check if auth key is valid
        bundle = StremioBundle()
        try:
            try:
                await bundle.auth.get_user_info(auth_key)
            except Exception as e:
                logger.exception(f"[{redact_token(token)}] Invalid auth key. Falling back to login: {e}")
                email = credentials.get("email")
                password = credentials.get("password")
                if email and password:
                    auth_key = await bundle.auth.login(email, password)
                    credentials["authKey"] = auth_key
                    await token_store.update_user_data(token, credentials)
                else:
                    return True  # true since we won't be able to update it again. so no need to try again.

            # 1. Check if addon is still installed
            try:
                addon_installed = await bundle.addons.is_addon_installed(auth_key)
                if not addon_installed:
                    logger.info(f"[{redact_token(token)}] User has not installed addon. Removing token from redis")
                    return True
            except Exception as e:
                logger.exception(f"[{redact_token(token)}] Failed to check if addon is installed: {e}")
                return False

            # 2. Extract settings and refresh
            user_settings = None
            if credentials.get("settings"):
                try:
                    user_settings = UserSettings(**credentials["settings"])
                except Exception as e:
                    logger.exception(f"[{redact_token(token)}] Failed to parse user settings: {e}")
                    return True  # if user doesn't have setting, we can't update the catalogs. so no need to try again.

            # Fetch fresh library
            library_items = await bundle.library.get_library_items(auth_key)

            dynamic_catalog_service = DynamicCatalogService(
                language=(user_settings.language if user_settings else "en-US"),
            )

            catalogs = await dynamic_catalog_service.get_dynamic_catalogs(
                library_items=library_items, user_settings=user_settings
            )

            # Translate catalogs
            if user_settings and user_settings.language:
                for cat in catalogs:
                    if name := cat.get("name"):
                        try:
                            cat["name"] = await translation_service.translate(name, user_settings.language)
                        except Exception as e:
                            logger.warning(f"Failed to translate catalog name '{name}': {e}")
                            continue

            logger.info(f"[{redact_token(token)}] Prepared {len(catalogs)} catalogs for background refresh")
            # sort catalogs by order in user settings
            if user_settings:
                order_map = {c.id: i for i, c in enumerate(user_settings.catalogs)}
                catalogs.sort(key=lambda x: order_map.get(get_config_id(x), 999))

            success = await bundle.addons.update_catalogs(auth_key, catalogs)

            # Update timestamp and invalidate cache only on success
            if success and update_timestamp:
                try:
                    # Update last_updated timestamp to current time
                    # This represents when the update completed successfully
                    now = datetime.now(timezone.utc)
                    last_updated_str = now.replace(microsecond=0).isoformat()
                    credentials["last_updated"] = last_updated_str
                    await token_store.update_user_data(token, credentials)
                    logger.debug(f"[{redact_token(token)}] Updated last_updated timestamp to {last_updated_str}")
                except Exception as e:
                    logger.warning(f"[{redact_token(token)}] Failed to update last_updated timestamp: {e}")

            return success

        except Exception as e:
            logger.exception(f"[{redact_token(token)}] Failed to update catalogs in background: {e}")
            return False
        finally:
            await bundle.close()

    async def trigger_update(self, token: str, credentials: dict[str, Any]) -> None:
        """
        Trigger a catalog update if needed.
        This function checks if update is needed and fires a background task.
        Uses in-memory lock to prevent duplicate updates.
        """
        # Check if already updating
        if token in self._updating_tokens:
            logger.debug(f"[{redact_token(token)}] Update already in progress, skipping")
            return

        # Check if update is needed
        if not self._needs_update(credentials):
            logger.debug(f"[{redact_token(token)}] Catalog update not needed yet")
            return

        # Add to lock and fire background update
        self._updating_tokens.add(token)
        logger.info(f"[{redact_token(token)}] Triggering catalog update")

        # Fire and forget background task
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
            # Always remove from lock
            self._updating_tokens.discard(token)


logger.info(f"Catalog updater initialized with refresh interval of {settings.CATALOG_REFRESH_INTERVAL_SECONDS} seconds")
catalog_updater = CatalogUpdater()
