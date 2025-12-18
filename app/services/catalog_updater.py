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
from app.services.stremio import StremioService
from app.services.token_store import token_store
from app.services.translation import translation_service

MAX_CONCURRENT_UPDATES = 5


async def refresh_catalogs_for_credentials(token: str, credentials: dict[str, Any]) -> bool:
    if not credentials:
        raise HTTPException(status_code=401, detail="Invalid token")

    auth_key = credentials.get("authKey")
    stremio = StremioService(auth_key=auth_key)

    try:
        if not await stremio.is_addon_installed(auth_key):
            logger.info(f"[{redact_token(token)}] Addon not installed. Skipping.")
            return True

        user_settings = _parse_settings(credentials)

        # Force fresh library
        library = await stremio.get_library_items(use_cache=False)

        catalog_service = DynamicCatalogService(stremio, language=user_settings.language or "en-US")
        catalogs = await catalog_service.get_dynamic_catalogs(library, user_settings)

        # Translation
        if user_settings.language:
            for cat in catalogs:
                if cat.get("name"):
                    cat["name"] = await translation_service.translate(cat["name"], user_settings.language)

        logger.info(f"[{redact_token(token)}] Prepared {len(catalogs)} catalogs")
        return await stremio.update_catalogs(catalogs, auth_key)

    except Exception as e:
        logger.exception(f"[{redact_token(token)}] Failed to update: {e}")
        raise e
    finally:
        await stremio.close()


def _parse_settings(credentials):
    try:
        if credentials.get("settings"):
            return UserSettings(**credentials["settings"])
    except Exception:
        pass
    return get_default_settings()


class BackgroundCatalogUpdater:
    def __init__(self) -> None:
        self.scheduler = AsyncIOScheduler(timezone="UTC")
        self.update_mode = settings.CATALOG_UPDATE_MODE

    def start(self) -> None:
        if self.scheduler.running:
            return

        if self.update_mode == "cron":
            self._schedule_cron()
        else:
            self._schedule_interval()
        self.scheduler.start()

    async def stop(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=True)

    def _schedule_cron(self):
        logger.info(f"Starting background updater (CRON): {settings.CATALOG_UPDATE_CRON_SCHEDULES}")
        defaults = {"func": self.refresh_all_tokens, "replace_existing": True, "max_instances": 1, "coalesce": True}
        for s in settings.CATALOG_UPDATE_CRON_SCHEDULES:
            self.scheduler.add_job(
                CronTrigger(hour=s["hour"], minute=s["minute"], timezone="UTC"), id=s["id"], **defaults
            )

    def _schedule_interval(self):
        sec = max(3600, settings.CATALOG_REFRESH_INTERVAL_SECONDS)
        logger.info(f"Starting background updater (INTERVAL): {sec}s")
        self.scheduler.add_job(
            self.refresh_all_tokens,
            trigger=IntervalTrigger(seconds=sec),
            id="catalog_refresh",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

    async def refresh_all_tokens(self) -> None:
        if not await self._check_redis_load():
            return

        tasks = []
        sem = asyncio.Semaphore(MAX_CONCURRENT_UPDATES)

        async def _safe_update(key, payload):
            if not payload.get("authKey"):
                return
            async with sem:
                try:
                    await refresh_catalogs_for_credentials(key, payload)
                except Exception:
                    pass  # Logged inside

        try:
            async for key, payload in token_store.iter_payloads():
                prefix = token_store.KEY_PREFIX
                tok = key[len(prefix) :] if key.startswith(prefix) else key  # noqa
                tasks.append(asyncio.create_task(_safe_update(tok, payload)))

            if tasks:
                logger.info(f"Refreshing {len(tasks)} tokens...")
                await asyncio.gather(*tasks)
        except Exception as e:
            logger.error(f"Scan failed: {e}")

    async def _check_redis_load(self):
        try:
            client = await token_store.get_client()
            info = await client.info("clients")
            connected = int(info.get("connected_clients", 0))
            limit = getattr(settings, "REDIS_CONNECTIONS_THRESHOLD", 1000)
            if connected > limit:
                logger.warning(f"Redis overloaded ({connected} > {limit}). Skipping.")
                return False
            return True
        except Exception:
            return True
