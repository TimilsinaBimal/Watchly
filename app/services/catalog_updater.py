import asyncio
import copy
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from loguru import logger

from app.core.config import settings
from app.core.security import redact_token
from app.services.auth import auth_service
from app.services.context import extract_settings
from app.services.manifest import manifest_service
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
        # Retain background task handles so they don't get GC'd mid-flight,
        # and so unhandled exceptions surface in logs.
        self._pending_tasks: set[asyncio.Task] = set()
        self._running: dict[str, asyncio.Task] = {}

    def _on_task_done(self, task: asyncio.Task) -> None:
        self._pending_tasks.discard(task)
        try:
            exc = task.exception()
        except asyncio.CancelledError:
            return
        if exc is not None:
            logger.error(f"Background catalog update task crashed: {exc!r}")

    async def wait_for(self, token: str) -> None:
        """Wait for a refresh running for this token, if there is one."""
        task = self._running.get(token)
        if task is not None:
            await asyncio.wait([task])

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

        user_settings = extract_settings(credentials)

        bundle = StremioBundle()
        try:
            auth_key = await auth_service.resolve_auth_key_with_bundle(bundle, credentials, token)

            if auth_key:
                try:
                    if not await bundle.addons.is_addon_installed(auth_key):
                        logger.info(f"[{redact_token(token)}] Addon not installed, skipping update")
                        return True
                except Exception:
                    logger.exception(f"[{redact_token(token)}] Failed to check addon install status")
                    return False

            # The manifest build only reads the cached library, and that cache is
            # re-fetched only when it is missing — every read renews its TTL. For an
            # active user this is the one place new watches reach the library and
            # the profiles, so refetch before rebuilding. Stremio only for now: Trakt
            # and Simkl report an outage or a rejected token as an empty history,
            # which a daily refetch would cache over the user's library.
            if user_settings.watch_history_source == "stremio":
                await manifest_service.cache_library_and_profiles(bundle, auth_key, user_settings, token)

            # Force a rebuild: this job exists to push a *fresh* catalog list to
            # Stremio, so reading the manifest cache would make it a no-op.
            manifest = await manifest_service.get_manifest_for_token(token, force_rebuild=True)
            catalogs = manifest.get("catalogs", [])

            if auth_key:
                success = await bundle.addons.update_catalogs(auth_key, catalogs)
            else:
                # No Stremio session to push to (Trakt/Simkl-only account).
                # Rebuilding the manifest above refreshed the caches; Stremio
                # picks up the new rows on its next periodic manifest pull.
                logger.info(f"[{redact_token(token)}] No Stremio auth; manifest refreshed for pull only")
                success = True

            if success and update_timestamp:
                try:
                    # Stamp what is stored now, not the credentials this refresh started
                    # with: a settings save or a Trakt token rotation may have replaced
                    # them since, and writing the old ones back would undo it.
                    stored = await token_store.get_user_data(token)
                    if stored is None:
                        logger.info(f"[{redact_token(token)}] Token removed during the refresh; not stamping it")
                    else:
                        stored = copy.deepcopy(stored)
                        stored["last_updated"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
                        await token_store.update_user_data(token, stored)
                        logger.debug(f"[{redact_token(token)}] Updated last_updated timestamp")
                except Exception as e:
                    logger.warning(f"[{redact_token(token)}] Failed to update timestamp: {e}")

            if success:
                # Rewriting the library and profiles drops every cached row. Build them
                # now so the next home screen doesn't wait on each one. Imported here
                # because the catalog service imports this module to trigger refreshes.
                from app.services.recommendation.catalog_service import catalog_service

                for catalog in catalogs:
                    # Stremio's home board skips a row with a required extra; that one is
                    # built when the user opens it in Discover.
                    if any(extra.get("isRequired") for extra in catalog.get("extra", [])):
                        continue
                    try:
                        await catalog_service.get_catalog(token, catalog["type"], catalog["id"])
                    except Exception as e:
                        # A row that fails to build comes back empty, so what gets here is
                        # the account (credentials gone, Stremio session lost), and every
                        # remaining row would hit it too.
                        logger.warning(f"[{redact_token(token)}] Stopped rebuilding rows: {type(e).__name__}")
                        break

            return success

        except Exception:
            logger.exception(f"[{redact_token(token)}] Failed to update catalogs in background")
            try:
                error_auth_key = credentials.get("authKey")
                if isinstance(error_auth_key, str) and error_auth_key:
                    description = (
                        "Movie and series recommendations based on your Stremio library.\n\n"
                        "⚠️ Status: Error\nFailed to update catalogs."
                    )
                    await bundle.addons.update_description(error_auth_key, description)
            except Exception as update_err:
                logger.warning(
                    f"[{redact_token(token)}] Failed to update addon description: {type(update_err).__name__}"
                )
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
        task = asyncio.create_task(self._update_task(token, credentials))
        self._pending_tasks.add(task)
        self._running[token] = task
        task.add_done_callback(self._on_task_done)

    async def _update_task(self, token: str, credentials: dict[str, Any]) -> None:
        """Background task that performs the actual catalog update."""
        try:
            success = await self.refresh_catalogs_for_credentials(token, credentials, update_timestamp=True)
            if success:
                logger.info(f"[{redact_token(token)}] Catalog update completed successfully")
            else:
                logger.warning(f"[{redact_token(token)}] Catalog update completed with failure")
        except Exception:
            logger.exception(f"[{redact_token(token)}] Catalog update task failed")
        finally:
            self._updating_tokens.discard(token)
            self._running.pop(token, None)


catalog_updater = CatalogUpdater()
