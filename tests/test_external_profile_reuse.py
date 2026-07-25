import asyncio

import pytest

from app.core.constants import PROFILE_SCORING_VERSION
from app.core.settings import UserSettings
from app.models.history import WatchHistory
from app.models.library import LibraryCollection, StremioLibraryItem
from app.models.profile import TasteProfile
from app.services.profile.scoring import ScoringService
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


class FakeBuilder:
    """Records incremental updates and folds the new ids into processed_items."""

    def __init__(self, calls: dict):
        self.calls = calls

    async def update_profile_incrementally(self, existing, new_items, content_type=None):
        self.calls["incremental"].append(content_type)
        existing.processed_items |= {scored.item.id for scored in new_items}
        return existing


def service():
    """ProfileService with the expensive build stubbed, so builds can be counted.

    __new__ skips __init__, which would construct a real vectorizer and TMDB client.
    ScoringService is real — it does no I/O.
    """
    svc = ProfileService.__new__(ProfileService)
    calls: dict[str, list] = {"full": [], "incremental": []}

    async def fake_full(collection, content_type, source):
        calls["full"].append(content_type)
        scored_ids = {i.id for i in collection.for_type(content_type).all_items()}
        return TasteProfile(source=source, scoring_version=PROFILE_SCORING_VERSION, processed_items=scored_ids)

    svc._build_from_collection = fake_full
    svc.scoring_service = ScoringService()
    svc.builder = FakeBuilder(calls)
    return svc, calls


def seed_cached_profile(lib: LibraryCollection, content_type: str = "movie"):
    """Store a profile alongside the bucket map it was built from.

    processed_items has to list the ids the profile actually scored — that is what
    the build planner diffs against.
    """
    typed = lib.for_type(content_type)
    profile = TasteProfile(
        source="trakt",
        scoring_version=PROFILE_SCORING_VERSION,
        processed_items={i.id for i in typed.all_items()},
    )
    asyncio.run(user_cache.set_profile_and_watched_sets(TOKEN, content_type, profile, set(), {"tt-cached"}))
    asyncio.run(user_cache.set_library_buckets(TOKEN, content_type, typed))


def build(svc, lib, content_type="movie", source="trakt"):
    return asyncio.run(svc._build_from_external_source(source, None, content_type, lib, token=TOKEN))


def test_unchanged_library_reuses_cached_profile(fake_redis):
    lib = library(loved=["tt1"], watched=["tt2"])
    seed_cached_profile(lib)
    svc, calls = service()

    profile, _, watched_imdb = build(svc, lib)

    assert calls == {"full": [], "incremental": []}
    assert watched_imdb == {"tt-cached"}
    assert profile.source == "trakt"


def test_added_title_is_folded_in_incrementally(fake_redis):
    """The whole point of the bucket map: a new title extends the profile instead
    of rebuilding it from scratch."""
    seed_cached_profile(library(loved=["tt1"]))
    svc, calls = service()

    build(svc, library(loved=["tt1", "tt3"]))

    assert calls["incremental"] == ["movie"]
    assert calls["full"] == []


def test_rerating_a_scored_title_forces_a_full_rebuild(fake_redis):
    """Identical id set — only the bucket moved. Scores accumulate additively, so
    the old rating's contribution can't be subtracted by adding more."""
    seed_cached_profile(library(watched=["tt1", "tt2"]))
    svc, calls = service()

    build(svc, library(loved=["tt1"], watched=["tt2"]))

    assert calls["full"] == ["movie"]
    assert calls["incremental"] == []


def test_removing_a_scored_title_forces_a_full_rebuild(fake_redis):
    seed_cached_profile(library(loved=["tt1"], watched=["tt2"]))
    svc, calls = service()

    build(svc, library(loved=["tt1"]))

    assert calls["full"] == ["movie"]
    assert calls["incremental"] == []


def test_second_build_of_an_unchanged_library_is_skipped(fake_redis):
    """Through the real entry point, which is what caches the profile the skip needs."""
    lib = library(loved=["tt1"])
    settings = UserSettings(catalogs=[], watch_history_source="trakt")
    svc, calls = service()

    asyncio.run(svc.build_and_cache_profile(TOKEN, "movie", lib, user_settings=settings))
    assert calls["full"] == ["movie"]  # nothing cached yet

    asyncio.run(svc.build_and_cache_profile(TOKEN, "movie", lib, user_settings=settings))
    assert calls["full"] == ["movie"]  # unchanged, so neither path runs again
    assert calls["incremental"] == []


def test_other_content_type_is_tracked_separately(fake_redis):
    lib = LibraryCollection(loved=[item("tt1", "movie"), item("tt9", "series")], source="trakt")
    seed_cached_profile(lib, "movie")
    svc, calls = service()

    build(svc, lib, "movie")
    assert calls["full"] == []

    build(svc, lib, "series")
    assert calls["full"] == ["series"]


def test_no_reuse_when_library_came_from_another_source(fake_redis):
    """A Stremio-sourced library says nothing about the Trakt history that gets
    fetched instead, so even a matching bucket map must not gate the rebuild."""
    stremio_lib = library(loved=["tt1"], source="stremio")
    seed_cached_profile(stremio_lib)
    svc, calls = service()

    async def fake_fetch(source, user_settings, token=None):
        return WatchHistory(items=[], source=source), False, False

    svc.fetch_external_watch_history = fake_fetch

    build(svc, stremio_lib)

    assert calls["full"] == ["movie"]


def test_bucket_map_distinguishes_rating_changes():
    watched_only = user_cache.bucket_map(library(watched=["tt1"]).for_type("movie"))
    promoted = user_cache.bucket_map(library(loved=["tt1"]).for_type("movie"))

    assert watched_only == {"tt1": "w"}
    assert promoted == {"tt1": "l"}
    assert watched_only != promoted


def test_external_items_get_real_scores_not_a_flat_constant():
    """External items used to be handed to the builder with score=50.0 and
    is_recent=False regardless of how they were watched, so completion, rewatch
    and recency never reached the profile — and nothing could be ranked."""
    from app.models.history import WatchHistoryItem
    from app.services.stremio.library import watch_history_item_to_library_item

    scoring = ScoringService()

    def score_for(**kwargs):
        history_item = WatchHistoryItem(imdb_id="tt1", type="movie", name="X", **kwargs)
        return scoring.process_item(watch_history_item_to_library_item(history_item, False, False))

    part_watched = score_for(completion=0.4, watch_count=1)
    watched_once = score_for(completion=1.0, watch_count=1)
    rewatched = score_for(completion=1.0, watch_count=4)

    # Three different viewing histories, three different scores. Previously all
    # three were 50.0.
    assert len({part_watched.score, watched_once.score, rewatched.score}) == 3
    assert part_watched.completion_rate < watched_once.completion_rate

    # A completed rewatch must keep its rewatch credit: the scorer drops the
    # rewatch bonus when flaggedWatched is set, so the converter must not set it.
    assert rewatched.is_rewatched
    assert not watched_once.is_rewatched


def test_ratings_still_map_to_buckets():
    """Bucketing is what reaches the profile as source_type, so it has to survive
    the conversion the profile build now relies on."""
    from app.models.history import WatchHistoryItem
    from app.services.stremio.library import watch_history_to_library_collection

    def one(rating, watch_count=1):
        return WatchHistoryItem(imdb_id=f"tt{rating}", type="movie", name="X", rating=rating, watch_count=watch_count)

    collection = watch_history_to_library_collection(WatchHistory(items=[one(9.5), one(7.5), one(4.0)], source="trakt"))

    assert [i.id for i in collection.loved] == ["tt9.5"]
    assert [i.id for i in collection.liked] == ["tt7.5"]
    assert [i.id for i in collection.watched] == ["tt4.0"]
