import asyncio
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from loguru import logger

from app.services.catalog import DynamicCatalogService
from app.services.stremio_service import StremioService
from app.services.token_store import token_store
from app.utils import redact_token

# Max number of concurrent updates to prevent overwhelming external APIs
MAX_CONCURRENT_UPDATES = 5


async def refresh_catalogs_for_credentials(credentials: dict[str, Any], auth_key: str | None = None) -> bool:
    """Regenerate catalogs for the provided credentials and push them to Stremio."""
    stremio_service = StremioService(
        username=credentials.get("username") or "",
        password=credentials.get("password") or "",
        auth_key=auth_key or credentials.get("authKey"),
    )
    try:
        library_items = await stremio_service.get_library_items()
        dynamic_catalog_service = DynamicCatalogService(stremio_service=stremio_service)

        catalogs = await dynamic_catalog_service.get_watched_loved_catalogs(library_items=library_items)
        catalogs += await dynamic_catalog_service.get_genre_based_catalogs(library_items=library_items)
        auth_key_or_username = credentials.get("authKey") or credentials.get("username")
        redacted = redact_token(auth_key_or_username) if auth_key_or_username else "unknown"
        logger.info(f"[{redacted}] Prepared {len(catalogs)} catalogs")
        auth_key = await stremio_service.get_auth_key()
        return await stremio_service.update_catalogs(catalogs, auth_key)
    finally:
        await stremio_service.close()


class BackgroundCatalogUpdater:
    """Periodic job that refreshes catalogs for every stored credential token."""

    def __init__(self, interval_seconds: int) -> None:
        self.interval_seconds = max(60, interval_seconds)
        self.scheduler = AsyncIOScheduler()

    def start(self) -> None:
        if self.scheduler.running:
            return

        logger.info(f"Starting background catalog updater. Interval: {self.interval_seconds}s")
        self.scheduler.add_job(
            self.refresh_all_tokens,
            trigger=IntervalTrigger(seconds=self.interval_seconds),
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
            if not self._has_credentials(payload):
                logger.debug(
                    f"Skipping token {self._mask_key(key)} with incomplete credentials",
                )
                return

            async with sem:
                try:
                    updated = await refresh_catalogs_for_credentials(payload)
                    logger.info(
                        f"Background refresh for {self._mask_key(key)} completed (updated={updated})",
                    )
                except Exception as exc:
                    logger.error(f"Background refresh failed for {self._mask_key(key)}: {exc}", exc_info=True)

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

    @staticmethod
    def _has_credentials(payload: dict[str, Any]) -> bool:
        return bool(payload.get("authKey") or (payload.get("username") and payload.get("password")))

    @staticmethod
    def _mask_key(key: str) -> str:
        suffix = key.split(":")[-1]
        return f"***{suffix[-6:]}"
