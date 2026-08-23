from datetime import datetime, timedelta, timezone

from app.models.library import LibraryCollection, StremioLibraryItem, StremioState
from app.services.profile.constants import SMART_SAMPLING_MAX_ITEMS
from app.services.profile.sampling import sample_items
from app.services.profile.scoring import ScoringService


def watched_item(item_id: str, completion: float, days_ago: int = 400) -> StremioLibraryItem:
    """A watched item whose score is driven by how much of it was watched."""
    duration = 6000
    return StremioLibraryItem(
        _id=item_id,
        type="movie",
        name=item_id,
        temp=False,
        removed=False,
        state=StremioState(
            duration=duration,
            timeWatched=int(duration * completion),
            timesWatched=1,
            lastWatched=datetime.now(timezone.utc) - timedelta(days=days_ago),
        ),
    )


def test_capped_sample_keeps_the_highest_scoring_items():
    """Regression: the quota slices took a prefix of each pool in library order, so
    a capped sample was an arbitrary subset rather than the strongest signals."""
    scoring = ScoringService()

    # Weakest first, so an unsorted prefix would pick exactly the wrong ones.
    completions = [0.1, 0.2, 0.3, 0.4, 0.9, 1.0]
    library = LibraryCollection(
        watched=[watched_item(f"tt{i}", c) for i, c in enumerate(completions)],
        source="stremio",
    )

    sampled = sample_items(library, "movie", scoring, max_items=2)

    assert len(sampled) == 2
    kept = {s.item.id for s in sampled}
    assert kept == {"tt4", "tt5"}, f"expected the two most-watched, got {kept}"


def test_everything_is_used_when_under_the_cap():
    scoring = ScoringService()
    library = LibraryCollection(
        watched=[watched_item("tt1", 0.5), watched_item("tt2", 1.0)],
        source="stremio",
    )

    sampled = sample_items(library, "movie", scoring, max_items=10)

    assert {s.item.id for s in sampled} == {"tt1", "tt2"}


def test_rated_items_get_their_own_quota():
    """Loved/liked draw from a 55% quota, so a barely-watched favourite still gets a
    slot against fully-watched but unrated titles.

    The cap is 10 rather than something tighter because the quotas are computed as
    int(max_items * 0.55), which rounds down to no slots at all below 2. Production
    only ever uses SMART_SAMPLING_MAX_ITEMS.
    """
    scoring = ScoringService()
    loved = watched_item("tt-loved", 0.3)
    loved.is_loved = True

    library = LibraryCollection(
        loved=[loved],
        watched=[watched_item(f"tt{i}", 1.0) for i in range(20)],
        source="stremio",
    )

    sampled = sample_items(library, "movie", scoring, max_items=10)

    assert "tt-loved" in {s.item.id for s in sampled}


def test_other_content_types_are_ignored():
    scoring = ScoringService()
    movie = watched_item("tt-movie", 1.0)
    series = watched_item("tt-series", 1.0)
    series.type = "series"

    library = LibraryCollection(watched=[movie, series], source="stremio")

    assert {s.item.id for s in sample_items(library, "movie", scoring)} == {"tt-movie"}


def test_quota_split_favours_rated_titles_over_the_watchlist():
    """A watchlist entry carries 0.3 evidence weight against a loved title's 3.0, so
    it should hold few slots — it costs the same TMDB lookups for a tenth the signal.

    All three pools are deliberately over-quota here: when a pool is short, backfill
    tops the sample up from the others and the split stops being observable.
    """
    scoring = ScoringService()
    loved = [watched_item(f"loved{i}", 0.9) for i in range(20)]
    for it in loved:
        it.is_loved = True

    library = LibraryCollection(
        loved=loved,
        added=[watched_item(f"added{i}", 0.0) for i in range(20)],
        watched=[watched_item(f"watched{i}", 1.0) for i in range(20)],
        source="stremio",
    )

    sampled = sample_items(library, "movie", scoring, max_items=30)

    kept = [s.item.id for s in sampled]
    assert len(kept) == 30
    assert sum(1 for k in kept if k.startswith("loved")) == 16  # 55%
    assert sum(1 for k in kept if k.startswith("added")) == 3  # 10%
    assert sum(1 for k in kept if k.startswith("watched")) == 11  # remainder


def test_production_cap_keeps_the_quota_split():
    """Guards the split at the real cap, not just the small one the other tests use:
    the quotas are int(cap * ratio), so they have to still add up at 200."""
    scoring = ScoringService()
    loved = [watched_item(f"loved{i}", 0.9) for i in range(300)]
    for it in loved:
        it.is_loved = True

    library = LibraryCollection(
        loved=loved,
        added=[watched_item(f"added{i}", 0.0) for i in range(300)],
        watched=[watched_item(f"watched{i}", 1.0) for i in range(300)],
        source="stremio",
    )

    kept = [s.item.id for s in sample_items(library, "movie", scoring)]

    assert len(kept) == SMART_SAMPLING_MAX_ITEMS
    assert sum(1 for k in kept if k.startswith("loved")) == 110  # 55%
    assert sum(1 for k in kept if k.startswith("added")) == 20  # 10%
    assert sum(1 for k in kept if k.startswith("watched")) == 70  # remainder


def test_enough_items_for_a_creator_to_recur():
    """The reason the cap went up: recommendation/creators.py drops anyone appearing
    fewer than twice, which a 30-item sample almost never produced."""
    assert SMART_SAMPLING_MAX_ITEMS >= 100
