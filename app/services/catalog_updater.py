import asyncio
from typing import Any, Dict

from loguru import logger

from app.services.catalog import DynamicCatalogService
from app.services.stremio_service import StremioService
from app.services.token_store import token_store


async def refresh_catalogs_for_credentials(
    credentials: Dict[str, Any], auth_key: str | None = None
) -> bool:
    """Regenerate catalogs for the provided credentials and push them to Stremio."""
    stremio_service = StremioService(
        username=credentials.get("username") or "",
        password=credentials.get("password") or "",
        auth_key=auth_key or credentials.get("authKey"),
    )
    try:
        library_items = await stremio_service.get_library_items()
        dynamic_catalog_service = DynamicCatalogService(stremio_service=stremio_service)

        catalogs = await dynamic_catalog_service.get_watched_loved_catalogs(
            library_items=library_items
        )
        catalogs += await dynamic_catalog_service.get_genre_based_catalogs(
            library_items=library_items
        )
        logger.info(
            "Prepared %s catalogs for %s",
            len(catalogs),
            "authKey" if credentials.get("authKey") else "username",
        )
        auth_key = await stremio_service.get_auth_key()
        return await stremio_service.update_catalogs(catalogs, auth_key)
    finally:
        await stremio_service.close()


class BackgroundCatalogUpdater:
    """Periodic job that refreshes catalogs for every stored credential token."""

    def __init__(self, interval_seconds: int) -> None:
        self.interval_seconds = max(60, interval_seconds)
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()

    def start(self) -> None:
        if self._task is not None:
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stop_event.set()
        await self._task
        self._task = None

    async def refresh_all_tokens(self) -> None:
        try:
            async for key, payload in token_store.iter_payloads():
                if not self._has_credentials(payload):
                    logger.debug("Skipping token %s with incomplete credentials", self._mask_key(key))
                    continue
                try:
                    updated = await refresh_catalogs_for_credentials(payload)
                    logger.info(
                        "Background refresh for %s completed (updated=%s)",
                        self._mask_key(key),
                        updated,
                    )
                except Exception as exc:
                    logger.error(
                        "Background refresh failed for %s: %s",
                        self._mask_key(key),
                        exc,
                        exc_info=True,
                    )
        except Exception as exc:
            logger.error("Catalog refresh scan failed: {}", exc, exc_info=True)

    async def _run(self) -> None:
        logger.info(
            "Background catalog updater started (interval=%ss)", self.interval_seconds
        )
        try:
            while not self._stop_event.is_set():
                await self.refresh_all_tokens()
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), timeout=self.interval_seconds
                    )
                except asyncio.TimeoutError:
                    continue
        finally:
            logger.info("Background catalog updater stopped")

    @staticmethod
    def _has_credentials(payload: Dict[str, Any]) -> bool:
        return bool(payload.get("authKey") or (payload.get("username") and payload.get("password")))

    @staticmethod
    def _mask_key(key: str) -> str:
        suffix = key.split(":")[-1]
        return f"***{suffix[-6:]}"
