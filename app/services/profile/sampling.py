from typing import Any

from app.models.scoring import ScoredItem
from app.services.profile.constants import SMART_SAMPLING_MAX_ITEMS
from app.services.scoring import ScoringService


class SmartSampler:
    """
    Smart sampling for profile building.

    Strategy:
    1. Always include all loved/liked/added items (strong signals)
    2. Fill remaining slots with top watched items by score
    3. Limit total to prevent excessive API calls
    """

    def __init__(self, scoring_service: ScoringService):
        """
        Initialize smart sampler.

        Args:
            scoring_service: Service for scoring items
        """
        self.scoring_service = scoring_service

    def sample_items(
        self,
        library_items: dict[str, list[dict[str, Any]]],
        content_type: str,
        max_items: int = SMART_SAMPLING_MAX_ITEMS,
    ) -> list[ScoredItem]:
        """
        Sample items for profile building.

        Args:
            library_items: Library items dict with 'loved', 'liked', 'watched', 'added' keys
            content_type: Content type to filter (movie/series)
            max_items: Maximum items to return

        Returns:
            List of ScoredItem objects
        """
        # Get all items of the requested type
        all_items = (
            library_items.get("loved", [])
            + library_items.get("liked", [])
            + library_items.get("watched", [])
            + library_items.get("added", [])
        )
        typed_items = [it for it in all_items if it.get("type") == content_type]

        if not typed_items:
            return []

        # Get added items (strong signal)
        added_item_ids = {it.get("_id") for it in library_items.get("added", [])}
        added_items = [it for it in typed_items if it.get("_id") in added_item_ids]

        # Separate loved/liked from watched items (excluding added to avoid double-counting)
        loved_liked_items = [
            it
            for it in typed_items
            if (it.get("_is_loved") or it.get("_is_liked")) and it.get("_id") not in added_item_ids
        ]
        watched_items = [
            it
            for it in typed_items
            if not (it.get("_is_loved") or it.get("_is_liked") or it.get("_id") in added_item_ids)
        ]

        # Always include strong signal items: Loved/Liked: 45%, Added: 20%
        strong_signal_items = loved_liked_items[: int(max_items * 0.45)] + added_items[: int(max_items * 0.20)]
        strong_signal_scored = [self.scoring_service.process_item(it) for it in strong_signal_items]

        # Score watched items and sort by score
        watched_scored = [self.scoring_service.process_item(it) for it in watched_items]
        watched_scored.sort(key=lambda x: x.score, reverse=True)

        # Fill remaining slots with top watched items
        remaining_slots = max(0, max_items - len(strong_signal_scored))
        top_watched = watched_scored[:remaining_slots]

        return strong_signal_scored + top_watched
