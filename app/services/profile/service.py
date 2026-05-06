from typing import Any

from loguru import logger

from app.core.settings import UserSettings
from app.models.history import WatchHistory, WatchHistoryItem
from app.models.library import LibraryCollection, StremioLibraryItem, StremioState
from app.models.profile import ScoredItem, TasteProfile
from app.services.profile.builder import ProfileBuilder
from app.services.profile.sampling import sample_items
from app.services.profile.scoring import ScoringService
from app.services.profile.vectorizer import ItemVectorizer
from app.services.recommendation.filtering import RecommendationFiltering
from app.services.stremio.library import stremio_library_to_watch_history
from app.services.tmdb.service import get_tmdb_service
from app.services.user_cache import user_cache


def _watch_history_item_to_scored(item: WatchHistoryItem) -> ScoredItem:
    """Convert a WatchHistoryItem to a ScoredItem for the existing vectorizer pipeline."""
    state_kwargs: dict[str, Any] = {}
    if item.last_watched:
        state_kwargs["lastWatched"] = item.last_watched
    state_kwargs["timesWatched"] = item.watch_count

    if item.completion < 1.0:
        state_kwargs["duration"] = 6000
        state_kwargs["timeWatched"] = int(6000 * item.completion)
    else:
        state_kwargs["timesWatched"] = max(item.watch_count, 1)
        state_kwargs["flaggedWatched"] = 1

    state = StremioState(**state_kwargs)

    is_loved = item.rating is not None and item.rating >= 9.0
    is_liked = item.rating is not None and 7.0 <= item.rating < 9.0

    lib_item = StremioLibraryItem(
        _id=item.imdb_id,
        type=item.type,
        name=item.name,
        state=state,
        temp=False,
        removed=False,
        _is_loved=is_loved,
        _is_liked=is_liked,
    )

    source_type = "loved" if is_loved else ("liked" if is_liked else "watched")

    return ScoredItem(
        item=lib_item,
        score=50.0,
        completion_rate=item.completion,
        is_rewatched=item.watch_count > 1,
        is_recent=False,
        source_type=source_type,
    )


class ProfileService:
    """Builds, updates, caches, and exposes user taste profiles."""

    def __init__(self, language: str = "en-US", tmdb_api_key: str | None = None):
        self.scoring_service = ScoringService()
        tmdb_service = get_tmdb_service(language=language, api_key=tmdb_api_key)
        vectorizer = ItemVectorizer(tmdb_service)
        self.builder = ProfileBuilder(vectorizer)

    async def build_profile_from_library(
        self,
        library_items: LibraryCollection,
        content_type: str,
        stremio_service: Any = None,
        auth_key: str | None = None,
    ) -> tuple[TasteProfile | None, set[int], set[str]]:
        """Build taste profile from library items and get watched sets."""
        watched_imdb, watched_tmdb = await RecommendationFiltering.get_exclusion_sets(
            stremio_service, library_items, auth_key
        )

        typed = library_items.for_type(content_type)
        if typed.is_empty():
            return None, watched_tmdb, watched_imdb

        sampled = sample_items(typed, content_type, self.scoring_service)
        profile = await self.builder.build_profile(sampled, content_type=content_type)
        if profile is not None:
            profile.source = "stremio"
        return profile, watched_tmdb, watched_imdb

    async def build_profile_incremental(
        self,
        library_items: LibraryCollection,
        content_type: str,
        token: str,
        stremio_service: Any = None,
        auth_key: str | None = None,
    ) -> tuple[TasteProfile | None, set[int], set[str]]:
        """Build profile incrementally if possible, fallback to full rebuild."""
        watched_imdb, watched_tmdb = await RecommendationFiltering.get_exclusion_sets(
            stremio_service, library_items, auth_key
        )

        typed = library_items.for_type(content_type)
        typed_items = typed.all_items()

        if not typed_items:
            return None, watched_tmdb, watched_imdb

        try:
            library_changed = await user_cache.has_library_changed(token, content_type, typed_items)

            if not library_changed:
                existing_profile = await user_cache.get_profile(token, content_type)
                if existing_profile:
                    return existing_profile, watched_tmdb, watched_imdb

            existing_profile = await user_cache.get_profile(token, content_type)

            if existing_profile:
                processed_ids = existing_profile.processed_items
                current_ids = {it.id for it in typed_items}
                is_legacy = not processed_ids and (existing_profile.genre_scores or existing_profile.director_scores)

                if not processed_ids.issubset(current_ids) or is_legacy:
                    reason = "Legacy profile detected" if is_legacy else "Items removed from library"
                    logger.debug(f"[{token[:8]}...] {reason}, falling back to full rebuild")
                else:
                    new_item_ids = current_ids - processed_ids

                    if not new_item_ids:
                        return existing_profile, watched_tmdb, watched_imdb

                    logger.debug(f"[{token[:8]}...] Found {len(new_item_ids)} new items, using incremental update")

                    def _is_new(it) -> bool:
                        item_id = it.id if hasattr(it, "id") else (it.get("_id") or it.get("id"))
                        return item_id in new_item_ids

                    new_library = LibraryCollection(
                        loved=[it for it in typed.loved if _is_new(it)],
                        liked=[it for it in typed.liked if _is_new(it)],
                        watched=[it for it in typed.watched if _is_new(it)],
                        added=[it for it in typed.added if _is_new(it)],
                    )

                    sampled = sample_items(new_library, content_type, self.scoring_service)

                    if not sampled:
                        return existing_profile, watched_tmdb, watched_imdb

                    updated_profile = await self.builder.update_profile_incrementally(
                        existing_profile, sampled, content_type=content_type
                    )

                    await user_cache.update_library_hash(token, content_type, typed_items)
                    return updated_profile, watched_tmdb, watched_imdb

        except Exception as e:
            logger.warning(f"[{token[:8]}...] Incremental update failed, falling back to full rebuild: {e}")

        logger.debug(f"[{token[:8]}...] Using full rebuild")
        profile, _, _ = await self.build_profile_from_library(library_items, content_type, stremio_service, auth_key)
        await user_cache.update_library_hash(token, content_type, typed_items)
        return profile, watched_tmdb, watched_imdb

    async def build_profile_from_watch_history(
        self,
        watch_history: WatchHistory,
        content_type: str,
        extra_exclusion_imdb: set[str] | None = None,
        source: str | None = None,
    ) -> tuple[TasteProfile | None, set[str]]:
        """Build taste profile from external watch history (Trakt/Simkl)."""
        typed_items = [it for it in watch_history.items if it.type == content_type]
        if not typed_items:
            return None, extra_exclusion_imdb or set()

        scored_items = [_watch_history_item_to_scored(it) for it in typed_items]
        profile = await self.builder.build_profile(scored_items, content_type=content_type)

        if profile is not None:
            profile.source = source or watch_history.source or "stremio"

        watched_imdb = watch_history.imdb_ids()
        if extra_exclusion_imdb:
            watched_imdb |= extra_exclusion_imdb

        return profile, watched_imdb

    async def build_and_cache_profile(
        self,
        token: str,
        content_type: str,
        library_items: LibraryCollection,
        stremio_service: Any = None,
        auth_key: str | None = None,
        user_settings: UserSettings | None = None,
    ) -> tuple[TasteProfile | None, set[int], set[str]]:
        """Build profile data and cache the profile and watched sets.

        Dispatches on user_settings.watch_history_source: uses Trakt or Simkl
        when the user connected those, otherwise the Stremio library.
        """
        source = user_settings.watch_history_source if user_settings else "stremio"

        # Drop a cached profile that was built from a different source than the
        # one the user has currently selected — otherwise switching sources in
        # the configure page silently keeps serving the old (wrong) profile.
        cached = await user_cache.get_profile(token, content_type)
        if cached and getattr(cached, "source", "stremio") != source:
            logger.info(
                f"[{token[:8]}...] Cached profile source '{cached.source}' "
                f"!= requested '{source}'; invalidating before rebuild."
            )
            await user_cache.invalidate_profile(token, content_type)
            await user_cache.invalidate_watched_sets(token, content_type)

        if source in ("trakt", "simkl"):
            profile, watched_tmdb, watched_imdb = await self._build_from_external_source(
                source, user_settings, content_type, library_items, token=token
            )
        else:
            profile, watched_tmdb, watched_imdb = await self.build_profile_incremental(
                library_items,
                content_type,
                token,
                stremio_service,
                auth_key,
            )

        await user_cache.set_profile_and_watched_sets(token, content_type, profile, watched_tmdb, watched_imdb)
        return profile, watched_tmdb, watched_imdb

    async def fetch_external_watch_history(
        self,
        source: str,
        user_settings: UserSettings | None,
        token: str | None = None,
    ) -> tuple[WatchHistory | None, bool, bool]:
        """Fetch watch history from Trakt or Simkl with token refresh + revoke handling.

        Returns (history, token_missing, token_revoked). On any non-auth failure
        history is None and both flags are False — caller decides whether to
        fall back. token_revoked=True implies the stored credential has been
        cleared from the user record by `_clear_revoked_token`.
        """
        import httpx

        watch_history: WatchHistory | None = None
        token_missing = False
        token_revoked = False

        if source == "trakt":
            if user_settings and user_settings.trakt_access_token:
                # Refresh proactively when within 7 days of expiry, then fetch.
                # On a 401 from get_history, attempt one reactive refresh + retry
                # before giving up — covers cases where expires_at was missing
                # or the server clock skewed past it.
                access_token, _ = await self._ensure_trakt_token_fresh(token, user_settings)

                from app.services.trakt import trakt_service

                try:
                    watch_history = await trakt_service.get_history(access_token)
                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 401 and user_settings.trakt_refresh_token and token:
                        logger.info(f"[{token[:8]}...] Trakt 401 on get_history; attempting reactive refresh.")
                        refreshed = await self._refresh_trakt_token(token, user_settings.trakt_refresh_token)
                        if refreshed:
                            try:
                                watch_history = await trakt_service.get_history(refreshed)
                            except httpx.HTTPStatusError as retry_e:
                                if retry_e.response.status_code in (401, 403):
                                    token_revoked = True
                                    logger.error(
                                        f"Trakt token still rejected after refresh (HTTP "
                                        f"{retry_e.response.status_code}). Clearing stored token."
                                    )
                                else:
                                    logger.error(
                                        f"Trakt history fetch failed after refresh (HTTP "
                                        f"{retry_e.response.status_code}: {retry_e})."
                                    )
                                watch_history = None
                        else:
                            token_revoked = True
                            logger.error("Trakt refresh failed; clearing stored token. User must reconnect Trakt.")
                    elif e.response.status_code in (401, 403):
                        token_revoked = True
                        logger.error(
                            f"Trakt token rejected (HTTP {e.response.status_code}). "
                            "Clearing stored token; user must reconnect Trakt."
                        )
                    else:
                        logger.error(
                            f"Trakt history fetch failed (HTTP {e.response.status_code}: {e}). "
                            "Falling back to Stremio library."
                        )
                        watch_history = None
                except Exception as e:
                    logger.error(
                        f"Trakt history fetch failed ({type(e).__name__}: {e}). Falling back to Stremio library."
                    )
                    watch_history = None
            else:
                token_missing = True
        elif source == "simkl":
            if user_settings and user_settings.simkl_access_token:
                from app.core.config import settings as app_settings
                from app.services.simkl import simkl_service

                try:
                    watch_history = await simkl_service.get_history(
                        user_settings.simkl_access_token,
                        app_settings.SIMKL_CLIENT_ID or "",
                    )
                except httpx.HTTPStatusError as e:
                    if e.response.status_code in (401, 403):
                        token_revoked = True
                        logger.error(
                            f"Simkl token rejected (HTTP {e.response.status_code}). "
                            "Clearing stored token; user must reconnect Simkl."
                        )
                    else:
                        logger.error(
                            f"Simkl history fetch failed (HTTP {e.response.status_code}: {e}). "
                            "Falling back to Stremio library."
                        )
                    watch_history = None
                except Exception as e:
                    logger.error(
                        f"Simkl history fetch failed ({type(e).__name__}: {e}). Falling back to Stremio library."
                    )
                    watch_history = None
            else:
                token_missing = True

        if token_missing:
            logger.error(
                f"watch_history_source='{source}' but no {source}_access_token in user settings. "
                "Falling back to Stremio library — the user likely needs to redo OAuth."
            )

        if token_revoked and token:
            await self._clear_revoked_token(token, source)

        return watch_history, token_missing, token_revoked

    async def fetch_external_library(
        self,
        source: str,
        user_settings: UserSettings | None,
        token: str | None = None,
    ) -> LibraryCollection | None:
        """Fetch external watch history and return it as a LibraryCollection.

        Returns None when no history could be fetched (missing/revoked token,
        network failure). The collection's `source` field carries the origin
        so cache layers can detect a source switch.
        """
        from app.services.stremio.library import watch_history_to_library_collection

        history, _, _ = await self.fetch_external_watch_history(source, user_settings, token)
        if history is None:
            return None
        return watch_history_to_library_collection(history)

    async def _build_from_external_source(
        self,
        source: str,
        user_settings: UserSettings | None,
        content_type: str,
        library: LibraryCollection,
        token: str | None = None,
    ) -> tuple[TasteProfile | None, set[int], set[str]]:
        """Build a profile from an external history source, falling back to the
        Stremio library when the external fetch fails or no token is set.

        When the passed-in library was already built from the same external
        source (load_user_context handles that), we avoid the duplicate fetch
        and read history straight off the library.
        """
        watch_history: WatchHistory | None = None

        if library.source == source:
            # context layer already pulled from the same source — reuse it.
            watch_history = WatchHistory(
                items=[
                    item
                    for items in (library.loved, library.liked, library.watched)
                    for item in (
                        WatchHistoryItem(
                            imdb_id=lib.id,
                            type=lib.type,
                            name=lib.name,
                            rating=(9.0 if lib.is_loved else (7.0 if lib.is_liked else None)),
                            watch_count=lib.state.timesWatched or (1 if lib.state.flaggedWatched else 0),
                            completion=(
                                1.0
                                if lib.state.flaggedWatched or (lib.state.timesWatched or 0) > 0
                                else (
                                    min((lib.state.timeWatched or 0) / lib.state.duration, 1.0)
                                    if lib.state.duration
                                    else 0.0
                                )
                            ),
                            last_watched=lib.state.lastWatched,
                            source=source,
                        )
                        for lib in items
                    )
                ],
                source=source,
            )
        else:
            watch_history, _, _ = await self.fetch_external_watch_history(source, user_settings, token)

        # An empty WatchHistory still counts as "the source spoke" — only fall back
        # on actual failure (None), not on a user with zero history.
        effective_source = source
        if watch_history is None:
            watch_history = stremio_library_to_watch_history(library)
            effective_source = "stremio"

        stremio_imdb = library.all_imdb_ids()
        profile, watched_imdb = await self.build_profile_from_watch_history(
            watch_history, content_type, extra_exclusion_imdb=stremio_imdb, source=effective_source
        )
        return profile, set(), watched_imdb

    async def _ensure_trakt_token_fresh(self, token: str | None, user_settings: UserSettings) -> tuple[str, bool]:
        """If the Trakt access token is within 7 days of expiry, refresh it.

        Returns (access_token_to_use, was_refreshed). Always returns the best
        token we have — even if refresh fails the original is returned so the
        caller can still attempt the request and surface the real failure.
        """
        import time as _time

        access_token = user_settings.trakt_access_token or ""
        expires_at = user_settings.trakt_token_expires_at or 0
        if not (token and user_settings.trakt_refresh_token and expires_at):
            return access_token, False

        seven_days = 7 * 24 * 60 * 60
        if _time.time() < expires_at - seven_days:
            return access_token, False

        logger.info(f"[{token[:8]}...] Trakt token within refresh window; refreshing proactively.")
        refreshed = await self._refresh_trakt_token(token, user_settings.trakt_refresh_token)
        if refreshed:
            return refreshed, True
        return access_token, False

    async def _refresh_trakt_token(self, token: str, refresh_token: str) -> str | None:
        """Refresh a Trakt access token and persist the new tokens.

        Returns the new access token on success, None on failure.
        """
        import time as _time

        from app.core.config import settings as app_settings
        from app.services.token_store import token_store
        from app.services.trakt import trakt_service

        redirect_uri = f"{app_settings.HOST_NAME}/auth/trakt/callback"
        try:
            data = await trakt_service.refresh_token(refresh_token, redirect_uri)
        except Exception as e:
            logger.warning(f"[{token[:8]}...] Trakt refresh_token call failed: {e}")
            return None

        new_access = data.get("access_token") or ""
        new_refresh = data.get("refresh_token") or refresh_token
        expires_in = int(data.get("expires_in") or 0)
        created_at = int(data.get("created_at") or _time.time())
        new_expires_at = created_at + expires_in if expires_in else 0
        if not new_access:
            logger.warning(f"[{token[:8]}...] Trakt refresh returned no access_token.")
            return None

        try:
            credentials = await token_store.get_user_data(token)
            if credentials:
                settings_dict = credentials.get("settings") or {}
                settings_dict["trakt_access_token"] = new_access
                settings_dict["trakt_refresh_token"] = new_refresh
                settings_dict["trakt_token_expires_at"] = new_expires_at
                credentials["settings"] = settings_dict
                await token_store.update_user_data(token, credentials)
                logger.info(f"[{token[:8]}...] Trakt token refreshed; new expiry={new_expires_at}.")
        except Exception as e:
            logger.warning(f"[{token[:8]}...] Failed to persist refreshed Trakt token: {e}")

        return new_access

    async def _clear_revoked_token(self, token: str, source: str) -> None:
        """Wipe a revoked external-source token from stored credentials.

        Called when Trakt/Simkl returns 401/403 — keeps the user from looping
        on a dead token forever. Their /configure page will show the source
        as disconnected on next visit so they can reconnect.
        """
        from app.services.token_store import token_store

        try:
            credentials = await token_store.get_user_data(token)
            if not credentials:
                return
            settings_dict = credentials.get("settings") or {}
            mutated = False
            if source == "trakt":
                for field in ("trakt_access_token", "trakt_refresh_token"):
                    if settings_dict.get(field):
                        settings_dict[field] = None
                        mutated = True
            elif source == "simkl":
                if settings_dict.get("simkl_access_token"):
                    settings_dict["simkl_access_token"] = None
                    mutated = True
            if mutated:
                credentials["settings"] = settings_dict
                await token_store.update_user_data(token, credentials)
                logger.info(f"[{token[:8]}...] Cleared revoked {source} credentials.")
        except Exception as e:
            logger.warning(f"[{token[:8]}...] Failed to clear revoked {source} token: {e}")
