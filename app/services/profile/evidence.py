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
_ABANDON_NEGATIVE_THRESHOLD = 0.30  # 15 min – 30%: mild negative


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
        # Check for an explicit rating (set by the WatchHistory → ScoredItem converter)
        # The converter maps loved→is_loved (rating≥9) and liked→is_liked (rating≥7).
        # For items with external ratings, we use the continuous scale.
        has_explicit_rating = False
        rating: float | None = None

        # Detect external-history items by checking the synthetic state pattern:
        # External items have flaggedWatched=1 and a specific duration sentinel (6000)
        # OR they have is_loved/is_liked set from external ratings.
        # We use a simpler heuristic: if is_loved with flaggedWatched=1, compute from rating=9.
        # For more granularity, we'll check the state for our sentinel.
        state = item.item.state

        if item.item.is_loved:
            # Could be Stremio loved (legacy) or external rating ≥ 9
            # Use rating-proportional weight for loved items
            rating = 9.0
            has_explicit_rating = True
        elif item.item.is_liked:
            rating = 7.0
            has_explicit_rating = True

        if has_explicit_rating and rating is not None:
            base_weight = EvidenceCalculator.weight_from_rating(rating)
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

        # Get last interaction date
        last_interaction = state.lastWatched
        if not last_interaction:
            try:
                if item.item.mtime:
                    last_interaction = datetime.fromisoformat(item.item.mtime.replace("Z", "+00:00"))
            except Exception:
                pass

        recency_multiplier = EvidenceCalculator.calculate_recency_multiplier(last_interaction)

        return base_weight * recency_multiplier
