from typing import Any

from loguru import logger

from app.models.history import WatchHistory, WatchHistoryItem
from app.models.library import LibraryCollection, StremioLibraryItem, StremioState
from app.models.profile import ScoredItem, TasteProfile
from app.services.profile.builder import ProfileBuilder
from app.services.profile.sampling import sample_items
from app.services.profile.scoring import ScoringService
from app.services.profile.vectorizer import ItemVectorizer
from app.services.recommendation.filtering import RecommendationFiltering
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
                current_ids = {it.get("_id", it.get("id")) for it in typed_items if it.get("_id", it.get("id"))}
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
    ) -> tuple[TasteProfile | None, set[str]]:
        """Build taste profile from external watch history (Trakt/Simkl)."""
        typed_items = [it for it in watch_history.items if it.type == content_type]
        if not typed_items:
            return None, extra_exclusion_imdb or set()

        scored_items = [_watch_history_item_to_scored(it) for it in typed_items]
        profile = await self.builder.build_profile(scored_items, content_type=content_type)

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
    ) -> tuple[TasteProfile | None, set[int], set[str]]:
        """Build profile data and cache the profile and watched sets."""
        profile, watched_tmdb, watched_imdb = await self.build_profile_incremental(
            library_items,
            content_type,
            token,
            stremio_service,
            auth_key,
        )
        await user_cache.set_profile_and_watched_sets(token, content_type, profile, watched_tmdb, watched_imdb)
        return profile, watched_tmdb, watched_imdb
