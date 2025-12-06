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
from app.services.stremio_service import StremioService
from app.services.token_store import token_store

# Max number of concurrent updates to prevent overwhelming external APIs
MAX_CONCURRENT_UPDATES = 5


async def refresh_catalogs_for_credentials(token: str, credentials: dict[str, Any]) -> bool:
    if not credentials:
        logger.warning(f"[{redact_token(token)}] Attempted to refresh catalogs with no credentials.")
        raise HTTPException(status_code=401, detail="Invalid or expired token. Please reconfigure the addon.")

    auth_key = credentials.get("authKey")
    stremio_service = StremioService(auth_key=auth_key)
    # check if user has addon installed or not
    try:
        addon_installed = await stremio_service.is_addon_installed(auth_key)
        if not addon_installed:
            logger.info("User has not installed addon. Removing token from redis")
            await token_store.delete_token(key=token)
            return True
    except Exception as e:
        logger.exception(f"Failed to check if addon is installed: {e}")

    try:
        library_items = await stremio_service.get_library_items()
        dynamic_catalog_service = DynamicCatalogService(stremio_service=stremio_service)

        # Ensure user_settings is available
        if credentials.get("settings"):
            try:
                user_settings = UserSettings(**credentials["settings"])
            except Exception as e:
                user_settings = get_default_settings()
                logger.warning(f"Failed to parse user settings from credentials: {e}")

        catalogs = await dynamic_catalog_service.get_dynamic_catalogs(
            library_items=library_items, user_settings=user_settings
        )
        logger.info(f"[{redact_token(token)}] Prepared {len(catalogs)} catalogs")
        return await stremio_service.update_catalogs(catalogs, auth_key)
    except Exception as e:
        logger.exception(f"Failed to update catalogs: {e}", exc_info=True)
        raise e
    finally:
        await stremio_service.close()


class BackgroundCatalogUpdater:
    """Periodic job that refreshes catalogs for every stored credential token.

    Supports two modes:
    - "cron": Runs twice daily at 12:00 PM UTC and 00:00 UTC (midnight)
    - "interval": Runs every CATALOG_REFRESH_INTERVAL_SECONDS
    """

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
            interval_seconds = max(3600, settings.CATALOG_REFRESH_INTERVAL_SECONDS)  # minimum 1 hour
            interval_hours = interval_seconds // 3600
            logger.info(f"Starting background catalog updater. Interval: {interval_seconds}s ({interval_hours} hours)")

            self.scheduler.add_job(
                self.refresh_all_tokens,
                trigger=IntervalTrigger(seconds=interval_seconds),
                id="catalog_refresh",
                replace_existing=True,
                max_instances=1,  # Prevent new job from starting if previous one is still running
                coalesce=True,  # If multiple runs are missed, only run once
            )

        self.scheduler.start()

    async def stop(self) -> None:
        if self.scheduler.running:
            logger.info("Stopping background catalog updater...")
            self.scheduler.shutdown(wait=True)  # Wait for running jobs to complete
            logger.info("Background catalog updater stopped.")

    async def refresh_all_tokens(self) -> None:
        """Refresh catalogs for all tokens concurrently with a semaphore."""
        tasks = []
        sem = asyncio.Semaphore(MAX_CONCURRENT_UPDATES)

        async def _update_safe(key: str, payload: dict[str, Any]) -> None:
            if not payload.get("authKey"):
                logger.debug(
                    f"Skipping token {redact_token(key)} with incomplete credentials",
                )
                return

            async with sem:
                try:
                    updated = await refresh_catalogs_for_credentials(key, payload)
                    logger.info(
                        f"Background refresh for {redact_token(key)} completed (updated={updated})",
                    )
                except Exception as exc:
                    logger.error(f"Background refresh failed for {redact_token(key)}: {exc}", exc_info=True)

        try:
            async for key, payload in token_store.iter_payloads():
                tasks.append(asyncio.create_task(_update_safe(key, payload)))

            if tasks:
                logger.info(f"Starting background refresh for {len(tasks)} tokens...")
                await asyncio.gather(*tasks)
                logger.info(f"Completed background refresh for {len(tasks)} tokens.")
            else:
                logger.info("No tokens found to refresh.")

        except Exception as exc:
            logger.error(f"Catalog refresh scan failed: {exc}", exc_info=True)
