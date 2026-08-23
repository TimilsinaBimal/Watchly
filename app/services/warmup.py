import asyncio
import json
import time
from typing import Any

from loguru import logger

from app.core.security import redact_token
from app.core.settings import UserSettings
from app.services.redis_service import redis_service
from app.services.stremio.service import StremioBundle

WARM_STATUS_KEY = "watchly:warm:{token}"
WARM_LOCK_KEY = "watchly:warmlock:{token}"

# Long enough for a big library, short enough that a process killed mid-warm
# doesn't leave the account looking busy for long.
LOCK_TTL_SECONDS = 900
STATUS_TTL_SECONDS = 3600


class WarmupService:
    """Builds a new account's caches off the request path.

    Saving a configuration used to await the whole thing — an external library
    fetch plus both profile builds — before the browser saw a manifest URL. The
    endpoint now enqueues prime() and returns, and the configure page follows
    along via get_status().
    """

    def __init__(self) -> None:
        # Retained so the task isn't garbage collected mid-flight, and so crashes
        # surface in the log rather than vanishing.
        self._tasks: set[asyncio.Task] = set()

    def enqueue(self, token: str, auth_key: str | None, user_settings: UserSettings) -> None:
        task = asyncio.create_task(self.prime(token, auth_key, user_settings))
        self._tasks.add(task)
        task.add_done_callback(self._on_done)

    def _on_done(self, task: asyncio.Task) -> None:
        self._tasks.discard(task)
        try:
            exc = task.exception()
        except asyncio.CancelledError:
            return
        if exc is not None:
            logger.error(f"Warm-up task crashed: {exc!r}")

    async def mark_pending(self, token: str) -> None:
        """Publish a status before returning from the request.

        Written by the endpoint rather than by prime() so a page that polls
        immediately never sees "unknown" while the task is still starting.
        """
        await self._set_status(token, "pending")

    async def prime(self, token: str, auth_key: str | None, user_settings: UserSettings) -> None:
        """Build library, profiles, manifest and Top Picks for an account."""
        lock_key = WARM_LOCK_KEY.format(token=token)
        if not await redis_service.set_nx(lock_key, "1", LOCK_TTL_SECONDS):
            logger.info(f"[{redact_token(token)}] Warm-up already running, skipping")
            return

        started = time.monotonic()
        try:
            from app.services.manifest import manifest_service

            await self._set_status(token, "building_profile")
            bundle = StremioBundle()
            try:
                library = await manifest_service.cache_library_and_profiles(bundle, auth_key, user_settings, token)
            finally:
                await bundle.close()
            item_count = len(library.all_items())
            await self._set_status(token, "profile_ready", f"{item_count} items in your library")
            logger.info(f"[{redact_token(token)}] Warm: profiles built in {time.monotonic() - started:.1f}s")

            await self._set_status(token, "warming_manifest", "Assembling your catalogs")
            step = time.monotonic()
            await manifest_service.get_manifest_for_token(token, force_rebuild=True)
            logger.info(f"[{redact_token(token)}] Warm: manifest built in {time.monotonic() - step:.1f}s")

            await self._set_status(token, "warming_catalogs", "Picking your first recommendations")
            step = time.monotonic()
            await self._warm_top_picks(token)
            logger.info(f"[{redact_token(token)}] Warm: top picks built in {time.monotonic() - step:.1f}s")

            await self._set_status(token, "ready")
            logger.info(f"[{redact_token(token)}] Warm-up finished in {time.monotonic() - started:.1f}s")
        except Exception as e:
            logger.exception(f"[{redact_token(token)}] Warm-up failed after {time.monotonic() - started:.1f}s: {e}")
            await self._set_status(token, "error", "We'll finish this when you first open the addon")
        finally:
            await redis_service.delete(lock_key)

    async def _warm_top_picks(self, token: str) -> None:
        """Build the two Top Picks rows so the first home screen is already cached.

        Only these two: every other row still builds on first request, but with the
        library and profile already cached it is a much cheaper build.
        """
        from app.services.recommendation.catalog_service import catalog_service

        async def warm(content_type: str) -> None:
            try:
                await catalog_service.get_catalog(token, content_type, "watchly.rec")
            except Exception as e:
                logger.warning(f"[{redact_token(token)}] Failed to warm {content_type} top picks: {e}")

        await asyncio.gather(warm("movie"), warm("series"))

    async def is_warming(self, token: str) -> bool:
        """Whether a warm-up currently holds the lock for this account."""
        return await redis_service.exists(WARM_LOCK_KEY.format(token=token))

    async def get_status(self, token: str) -> dict[str, Any]:
        raw = await redis_service.get(WARM_STATUS_KEY.format(token=token))
        if not raw:
            return {"state": "unknown"}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"state": "unknown"}

    async def _set_status(self, token: str, state: str, detail: str | None = None) -> None:
        payload = {"state": state, "updated_at": int(time.time())}
        if detail:
            payload["detail"] = detail
        await redis_service.set(WARM_STATUS_KEY.format(token=token), json.dumps(payload), STATUS_TTL_SECONDS)


warmup_service = WarmupService()
