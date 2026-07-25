import asyncio

import pytest

from app.core.constants import PROFILE_SCORING_VERSION
from app.core.settings import UserSettings
from app.models.history import WatchHistory
from app.models.library import LibraryCollection, StremioLibraryItem
from app.models.profile import TasteProfile
from app.services.profile.service import ProfileService
from app.services.user_cache import user_cache

TOKEN = "tok_external"


class FakeRedis:
    def __init__(self):
        self.data: dict[str, str] = {}

    async def get(self, key: str):
        return self.data.get(key)

    async def set(self, key: str, value, ttl=None):
        self.data[key] = value
        return True

    async def delete(self, key: str):
        self.data.pop(key, None)

    async def expire(self, key: str, ttl: int):
        return True


@pytest.fixture
def fake_redis(monkeypatch):
    fake = FakeRedis()
    for name in ("get", "set", "delete", "expire"):
        monkeypatch.setattr(f"app.services.user_cache.redis_service.{name}", getattr(fake, name))
    return fake


def item(item_id: str, content_type: str = "movie") -> StremioLibraryItem:
    return StremioLibraryItem(_id=item_id, type=content_type, name=item_id, temp=False, removed=False)


def library(loved=(), liked=(), watched=(), source="trakt") -> LibraryCollection:
    return LibraryCollection(
        loved=[item(i) for i in loved],
        liked=[item(i) for i in liked],
        watched=[item(i) for i in watched],
        source=source,
    )


def service():
    """ProfileService with the expensive build stubbed, so we can count rebuilds.

    __new__ skips __init__, which would construct a real vectorizer and TMDB client.
    """
    svc = ProfileService.__new__(ProfileService)
    rebuilds = []

    async def fake_build(watch_history, content_type, extra_exclusion_imdb=None, source=None):
        rebuilds.append(content_type)
        return TasteProfile(source=source or "trakt", scoring_version=PROFILE_SCORING_VERSION), {"tt-rebuilt"}

    svc.build_profile_from_watch_history = fake_build
    return svc, rebuilds


def seed_cached_profile(lib: LibraryCollection, content_type: str = "movie"):
    """Store a profile plus the signature it was built from."""
    asyncio.run(
        user_cache.set_profile_and_watched_sets(
            TOKEN,
            content_type,
            TasteProfile(source="trakt", scoring_version=PROFILE_SCORING_VERSION),
            set(),
            {"tt-cached"},
        )
    )
    asyncio.run(user_cache.update_library_signature(TOKEN, content_type, lib.for_type(content_type)))


def test_unchanged_library_reuses_cached_profile(fake_redis):
    lib = library(loved=["tt1"], watched=["tt2"])
    seed_cached_profile(lib)
    svc, rebuilds = service()

    profile, watched_tmdb, watched_imdb = asyncio.run(
        svc._build_from_external_source("trakt", None, "movie", lib, token=TOKEN)
    )

    assert rebuilds == []
    assert watched_imdb == {"tt-cached"}
    assert profile.source == "trakt"


def test_rerating_an_existing_title_forces_a_rebuild(fake_redis):
    """The id set is identical here — only the bucket moved. An id-only hash would
    treat this as unchanged and keep serving a profile built from the old rating."""
    seed_cached_profile(library(watched=["tt1", "tt2"]))
    svc, rebuilds = service()

    promoted = library(loved=["tt1"], watched=["tt2"])
    _, _, watched_imdb = asyncio.run(svc._build_from_external_source("trakt", None, "movie", promoted, token=TOKEN))

    assert rebuilds == ["movie"]
    assert watched_imdb == {"tt-rebuilt"}


def test_added_title_forces_a_rebuild(fake_redis):
    seed_cached_profile(library(loved=["tt1"]))
    svc, rebuilds = service()

    asyncio.run(svc._build_from_external_source("trakt", None, "movie", library(loved=["tt1", "tt3"]), token=TOKEN))

    assert rebuilds == ["movie"]


def test_second_build_of_an_unchanged_library_is_skipped(fake_redis):
    """Through the real entry point, which is what caches the profile the skip needs."""
    lib = library(loved=["tt1"])
    settings = UserSettings(catalogs=[], watch_history_source="trakt")
    svc, rebuilds = service()

    asyncio.run(svc.build_and_cache_profile(TOKEN, "movie", lib, user_settings=settings))
    assert rebuilds == ["movie"]  # nothing cached yet

    asyncio.run(svc.build_and_cache_profile(TOKEN, "movie", lib, user_settings=settings))
    assert rebuilds == ["movie"]  # signature and profile both cached, so no rebuild


def test_other_content_type_is_tracked_separately(fake_redis):
    lib = LibraryCollection(loved=[item("tt1", "movie"), item("tt9", "series")], source="trakt")
    seed_cached_profile(lib, "movie")
    svc, rebuilds = service()

    asyncio.run(svc._build_from_external_source("trakt", None, "movie", lib, token=TOKEN))
    assert rebuilds == []

    asyncio.run(svc._build_from_external_source("trakt", None, "series", lib, token=TOKEN))
    assert rebuilds == ["series"]


def test_no_reuse_when_library_came_from_another_source(fake_redis):
    """A Stremio-sourced library says nothing about the Trakt history that gets
    fetched instead, so even a matching signature must not gate the rebuild."""
    stremio_lib = library(loved=["tt1"], source="stremio")
    seed_cached_profile(stremio_lib)
    svc, rebuilds = service()

    async def fake_fetch(source, user_settings, token=None):
        return WatchHistory(items=[], source=source), False, False

    svc.fetch_external_watch_history = fake_fetch

    asyncio.run(svc._build_from_external_source("trakt", None, "movie", stremio_lib, token=TOKEN))

    assert rebuilds == ["movie"]


def test_external_items_get_real_scores_not_a_flat_constant():
    """External items used to be handed to the builder with score=50.0 and
    is_recent=False regardless of how they were watched, so completion, rewatch
    and recency never reached the profile — and nothing could be ranked."""
    from app.models.history import WatchHistoryItem
    from app.services.profile.scoring import ScoringService
    from app.services.profile.service import _watch_history_item_to_library_item

    scoring = ScoringService()

    def score_for(**kwargs):
        item = WatchHistoryItem(imdb_id="tt1", type="movie", name="X", **kwargs)
        return scoring.process_item(_watch_history_item_to_library_item(item))

    part_watched = score_for(completion=0.4, watch_count=1)
    watched_once = score_for(completion=1.0, watch_count=1)
    rewatched = score_for(completion=1.0, watch_count=4)

    # Three different viewing histories, three different scores. Previously all
    # three were 50.0.
    assert len({part_watched.score, watched_once.score, rewatched.score}) == 3
    assert part_watched.completion_rate < watched_once.completion_rate

    # A completed rewatch must keep its rewatch credit: the scorer drops the
    # rewatch bonus when flaggedWatched is set, so the adapter must not set it.
    assert rewatched.is_rewatched
    assert not watched_once.is_rewatched

    # Ratings still map to the same buckets the recommendation code keys on.
    assert score_for(rating=9.5).source_type == "loved"
    assert score_for(rating=7.5).source_type == "liked"
    assert score_for(rating=None).source_type == "watched"
