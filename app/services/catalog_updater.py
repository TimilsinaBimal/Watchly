import asyncio
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import HTTPException
from loguru import logger

from app.core.config import settings
from app.core.security import redact_token
from app.core.settings import UserSettings, get_default_settings
from app.services.catalog import DynamicCatalogService
from app.services.stremio.service import StremioBundle
from app.services.token_store import token_store
from app.services.translation import translation_service

# Max number of concurrent updates to prevent overwhelming external APIs
MAX_CONCURRENT_UPDATES = 5


async def refresh_catalogs_for_credentials(token: str, credentials: dict[str, Any]) -> bool:
    if not credentials:
        logger.warning(f"[{redact_token(token)}] Attempted to refresh catalogs with no credentials.")
        raise HTTPException(status_code=401, detail="Invalid or expired token. Please reconfigure the addon.")

    auth_key = credentials.get("authKey")
    bundle = StremioBundle()

    try:
        if not auth_key:
            # Fallback to login if possible
            email = credentials.get("email")
            password = credentials.get("password")
            if email and password:
                auth_key = await bundle.auth.login(email, password)
                credentials["authKey"] = auth_key
                await token_store.update_user_data(token, credentials)
            else:
                logger.warning(f"[{redact_token(token)}] No authKey or credentials for refresh.")
                return False

        # 1. Check if addon is still installed
        try:
            addon_installed = await bundle.addons.is_addon_installed(auth_key)
            if not addon_installed:
                logger.info(f"[{redact_token(token)}] User has not installed addon. Removing token from redis")
                # We could delete the token here: await token_store.delete_token(token)
                return True
        except Exception as e:
            logger.warning(f"[{redact_token(token)}] Failed to check if addon is installed: {e}")

        # 2. Extract settings and refresh
        user_settings = get_default_settings()
        if credentials.get("settings"):
            try:
                user_settings = UserSettings(**credentials["settings"])
            except Exception as e:
                logger.warning(f"[{redact_token(token)}] Failed to parse user settings: {e}")

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
                    except Exception:
                        pass

        logger.info(f"[{redact_token(token)}] Prepared {len(catalogs)} catalogs for background refresh")
        return await bundle.addons.update_catalogs(auth_key, catalogs)

    except Exception as e:
        logger.exception(f"[{redact_token(token)}] Failed to update catalogs in background: {e}")
        return False
    finally:
        await bundle.close()


class BackgroundCatalogUpdater:
    """Periodic job that refreshes catalogs for every stored credential token."""

    def __init__(self) -> None:
        self.scheduler = AsyncIOScheduler(timezone="UTC")
        self.update_mode = settings.CATALOG_UPDATE_MODE

    def start(self) -> None:
        if self.scheduler.running:
            return

        if self.update_mode == "cron":
            logger.info(f"Starting background catalog updater. Schedule: {settings.CATALOG_UPDATE_CRON_SCHEDULES}")
            job_defaults = {
                "func": self.refresh_all_tokens,
                "replace_existing": True,
                "max_instances": 1,
                "coalesce": True,
            }
            for schedule in settings.CATALOG_UPDATE_CRON_SCHEDULES:
                self.scheduler.add_job(
                    trigger=CronTrigger(hour=schedule["hour"], minute=schedule["minute"], timezone="UTC"),
                    id=schedule["id"],
                    **job_defaults,
                )
        else:  # interval mode
            interval_seconds = max(3600, settings.CATALOG_REFRESH_INTERVAL_SECONDS)
            interval_hours = interval_seconds // 3600
            logger.info(f"Starting background catalog updater. Interval: {interval_seconds}s ({interval_hours} hours)")

            self.scheduler.add_job(
                self.refresh_all_tokens,
                trigger=IntervalTrigger(seconds=interval_seconds),
                id="catalog_refresh",
                replace_existing=True,
                max_instances=1,
                coalesce=True,
            )

        self.scheduler.start()

    async def stop(self) -> None:
        if self.scheduler.running:
            logger.info("Stopping background catalog updater...")
            self.scheduler.shutdown(wait=True)
            logger.info("Background catalog updater stopped.")

    async def refresh_all_tokens(self) -> None:
        """Refresh catalogs for all tokens concurrently with a semaphore."""
        tasks = []
        sem = asyncio.Semaphore(MAX_CONCURRENT_UPDATES)

        async def _update_safe(key: str, payload: dict[str, Any]) -> None:
            async with sem:
                try:
                    updated = await refresh_catalogs_for_credentials(key, payload)
                    logger.info(
                        f"Background refresh for {redact_token(key)} completed (updated={updated})",
                    )
                except Exception as exc:
                    logger.error(f"Background refresh failed for {redact_token(key)}: {exc}")

        try:
            # Check Redis connections
            try:
                client = await token_store._get_client()
                info = await client.info(section="clients")
                connected = int(info.get("connected_clients", 0))
                threshold = getattr(settings, "REDIS_CONNECTIONS_THRESHOLD", 1000)
                if connected > threshold:
                    logger.warning(f"Redis connected clients {connected} exceed threshold; skipping refresh.")
                    return
            except Exception as exc:
                logger.warning(f"Failed to check Redis client info before refresh: {exc}")

            async for key, payload in token_store.iter_payloads():
                prefix = token_store.KEY_PREFIX
                tok = key[len(prefix) :] if key.startswith(prefix) else key  # noqa
                tasks.append(asyncio.create_task(_update_safe(tok, payload)))

            if tasks:
                logger.info(f"Starting background refresh for {len(tasks)} tokens...")
                await asyncio.gather(*tasks)
                logger.info(f"Completed background refresh for {len(tasks)} tokens.")
            else:
                logger.info("No tokens found to refresh.")

        except Exception as exc:
            logger.error(f"Catalog refresh scan failed: {exc}")
