from datetime import datetime, timezone

from app.models.history import WatchHistory, WatchHistoryItem
from app.services.profile.evidence import EvidenceCalculator
from app.services.profile.scoring import ScoringService
from app.services.stremio.library import watch_history_to_library_collection


def weights(*items: WatchHistoryItem) -> dict[str, float]:
    library = watch_history_to_library_collection(WatchHistory(items=list(items), source="trakt"))
    scoring = ScoringService()
    return {it.id: EvidenceCalculator.calculate_evidence_weight(scoring.process_item(it)) for it in library.all_items()}


def trakt_item(imdb_id: str, rating: float | None, watched: bool = True) -> WatchHistoryItem:
    return WatchHistoryItem(
        imdb_id=imdb_id,
        type="movie",
        name=imdb_id,
        rating=rating,
        watch_count=1 if watched else 0,
        completion=1.0 if watched else 0.0,
        last_watched=datetime.now(timezone.utc),
        source="trakt",
    )


def test_low_external_rating_counts_against_the_title():
    """Regression: ratings below 7 were dropped on conversion, so a watched title
    rated 2/10 added to the profile exactly like an unrated one."""
    w = weights(
        trakt_item("tt0000001", None),
        trakt_item("tt0000002", 2.0),
        trakt_item("tt0000003", 2.0, watched=False),
        trakt_item("tt0000004", 9.0),
    )

    assert w["tt0000002"] < 0
    assert w["tt0000003"] < 0
    assert w["tt0000002"] < w["tt0000001"] < w["tt0000004"]
