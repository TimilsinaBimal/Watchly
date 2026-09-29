import math
from datetime import datetime, timezone
from typing import Literal

from app.models.profile import ScoredItem
from app.services.profile.constants import (
    EVIDENCE_WEIGHT_ADDED,
    EVIDENCE_WEIGHT_LIKED,
    EVIDENCE_WEIGHT_LOVED,
    EVIDENCE_WEIGHT_WATCHED_HIGH,
    EVIDENCE_WEIGHT_WATCHED_MEDIUM,
    RECENCY_HALF_LIFE_DAYS,
)

# Abandonment thresholds (in minutes of watch time)
_ABANDON_IGNORE_MINUTES = 15  # < 15 min: too short, ignore


class EvidenceCalculator:
    """
    Calculates evidence weights for user interactions.

    Supports both legacy Stremio interaction types and explicit 1-10 ratings
    from external sources (Trakt, Simkl).
    """

    @staticmethod
    def get_interaction_type(item: ScoredItem) -> Literal["loved", "liked", "watched_high", "watched_medium", "added"]:
        """Determine interaction type from scored item."""
        if item.item.is_loved:
            return "loved"
        if item.item.is_liked:
            return "liked"
        if item.completion_rate >= 0.8:
            return "watched_high"
        if item.completion_rate >= 0.4:
            return "watched_medium"
        if not item.item.temp and not item.item.removed and item.completion_rate < 0.4:
            return "added"
        return "watched_medium"

    @staticmethod
    def get_base_weight(interaction_type: str) -> float:
        """Get base evidence weight for interaction type (legacy bucket system)."""
        weights = {
            "loved": EVIDENCE_WEIGHT_LOVED,
            "liked": EVIDENCE_WEIGHT_LIKED,
            "watched_high": EVIDENCE_WEIGHT_WATCHED_HIGH,
            "watched_medium": EVIDENCE_WEIGHT_WATCHED_MEDIUM,
            "added": EVIDENCE_WEIGHT_ADDED,
        }
        return weights.get(interaction_type, EVIDENCE_WEIGHT_WATCHED_MEDIUM)

    @staticmethod
    def weight_from_rating(rating: float) -> float:
        """
        Continuous evidence weight from an explicit 1-10 rating.

        Positive: 5→0.3, 6→0.8, 7→1.3, 8→1.8, 9→2.5, 10→3.0
        Negative: 1→-1.5, 2→-1.0, 3→-0.5, 4→-0.1
        """
        if rating >= 5:
            return max(0.1, (rating - 4) / 2)
        return (rating - 5) / 2

    @staticmethod
    def weight_from_completion(completion: float, watch_time_minutes: float | None = None) -> float:
        """
        Evidence weight for unrated items based on watch completion.

        Implements abandonment detection:
        - < 15 min watched: ignore (weight 0.0)
        - 15 min to 30% completion: mild negative (-0.2)
        - 30%-70% completion: neutral (0.0)
        - > 70% completion: positive (1.0)
        """
        # If we have actual watch time, use the abandonment thresholds
        if watch_time_minutes is not None and watch_time_minutes < _ABANDON_IGNORE_MINUTES:
            return 0.0

        if completion >= 0.7:
            return 1.0
        if completion >= 0.3:
            return 0.0  # Ambiguous — neutral
        if watch_time_minutes is not None and watch_time_minutes >= _ABANDON_IGNORE_MINUTES:
            return -0.2  # Gave it a fair shot and quit
        # Low completion without enough info — treat as neutral
        return 0.0

    @staticmethod
    def calculate_recency_multiplier(last_interaction: datetime | None) -> float:
        """Calculate recency multiplier using exponential decay."""
        if not last_interaction:
            return 0.5

        now = datetime.now(timezone.utc)
        if last_interaction.tzinfo is None:
            last_interaction = last_interaction.replace(tzinfo=timezone.utc)

        days_ago = (now - last_interaction).days
        if days_ago < 0:
            return 1.0

        multiplier = math.exp(-days_ago / RECENCY_HALF_LIFE_DAYS)
        return max(0.1, multiplier)

    @staticmethod
    def calculate_evidence_weight(item: ScoredItem) -> float:
        """
        Calculate final evidence weight for an item.

        Uses explicit rating if available (from external history sources),
        otherwise falls back to the legacy interaction-type bucket system.
        Abandonment detection is applied for unrated items.
        """
        # Stremio loves and external ratings >= 9 both arrive as is_loved, likes and
        # ratings >= 7 as is_liked, so they weigh as a 9 and a 7 on the rating scale.
        state = item.item.state

        if item.item.is_loved:
            base_weight = EvidenceCalculator.weight_from_rating(9.0)
        elif item.item.is_liked:
            base_weight = EvidenceCalculator.weight_from_rating(7.0)
        else:
            # Check for abandonment on unrated items
            watch_time_minutes: float | None = None
            if state.duration > 0 and state.timeWatched > 0:
                watch_time_minutes = state.timeWatched / 60.0

            completion = item.completion_rate

            # Use completion-based weight with abandonment detection
            completion_weight = EvidenceCalculator.weight_from_completion(completion, watch_time_minutes)

            if (
                completion_weight == 0.0
                and watch_time_minutes is not None
                and watch_time_minutes < _ABANDON_IGNORE_MINUTES
            ):
                # Too short, skip this item entirely
                return 0.0

            if completion_weight != 0.0:
                base_weight = completion_weight
            else:
                # Fall back to legacy bucket system for ambiguous cases
                interaction_type = EvidenceCalculator.get_interaction_type(item)
                base_weight = EvidenceCalculator.get_base_weight(interaction_type)

        recency_multiplier = EvidenceCalculator.calculate_recency_multiplier(item.item.last_interaction)

        return base_weight * recency_multiplier
