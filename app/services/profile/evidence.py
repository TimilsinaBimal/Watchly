import math
from datetime import datetime, timezone
from typing import Literal

from app.models.scoring import ScoredItem
from app.services.profile.constants import (
    EVIDENCE_WEIGHT_ADDED,
    EVIDENCE_WEIGHT_LIKED,
    EVIDENCE_WEIGHT_LOVED,
    EVIDENCE_WEIGHT_WATCHED_HIGH,
    EVIDENCE_WEIGHT_WATCHED_MEDIUM,
    RECENCY_HALF_LIFE_DAYS,
)


class EvidenceCalculator:
    """
    Calculates evidence weights for user interactions.

    Pure function: no side effects, easy to test.
    """

    @staticmethod
    def get_interaction_type(item: ScoredItem) -> Literal["loved", "liked", "watched_high", "watched_medium", "added"]:
        """
        Determine interaction type from scored item.

        Args:
            item: ScoredItem with interaction data

        Returns:
            Interaction type string
        """
        if item.item.is_loved:
            return "loved"
        if item.item.is_liked:
            return "liked"
        if item.completion_rate >= 0.8:
            return "watched_high"
        if item.completion_rate >= 0.4:
            return "watched_medium"
        # Check if added to library (not watched, not removed, not temp)
        if not item.item.temp and not item.item.removed and item.completion_rate < 0.4:
            return "added"
        return "watched_medium"  # Fallback

    @staticmethod
    def get_base_weight(interaction_type: str) -> float:
        """
        Get base evidence weight for interaction type.

        Args:
            interaction_type: Type of interaction

        Returns:
            Base weight value
        """
        weights = {
            "loved": EVIDENCE_WEIGHT_LOVED,
            "liked": EVIDENCE_WEIGHT_LIKED,
            "watched_high": EVIDENCE_WEIGHT_WATCHED_HIGH,
            "watched_medium": EVIDENCE_WEIGHT_WATCHED_MEDIUM,
            "added": EVIDENCE_WEIGHT_ADDED,
        }
        return weights.get(interaction_type, EVIDENCE_WEIGHT_WATCHED_MEDIUM)

    @staticmethod
    def calculate_recency_multiplier(last_interaction: datetime | None) -> float:
        """
        Calculate recency multiplier using exponential decay.

        Args:
            last_interaction: When the interaction occurred

        Returns:
            Multiplier (1.0 for recent, <1.0 for old)
        """
        if not last_interaction:
            return 0.5  # No date = old, reduce weight

        now = datetime.now(timezone.utc)
        if last_interaction.tzinfo is None:
            last_interaction = last_interaction.replace(tzinfo=timezone.utc)

        days_ago = (now - last_interaction).days
        if days_ago < 0:
            return 1.0  # Future date = treat as recent

        # Exponential decay: multiplier = exp(-days / half_life)
        multiplier = math.exp(-days_ago / RECENCY_HALF_LIFE_DAYS)
        return max(0.1, multiplier)  # Minimum 0.1 to keep some signal

    @staticmethod
    def calculate_evidence_weight(item: ScoredItem) -> float:
        """
        Calculate final evidence weight for an item.

        Combines base weight (interaction type) with recency multiplier.

        Args:
            item: ScoredItem with interaction data

        Returns:
            Final evidence weight
        """
        interaction_type = EvidenceCalculator.get_interaction_type(item)
        base_weight = EvidenceCalculator.get_base_weight(interaction_type)

        # Get last interaction date
        last_interaction = item.item.state.lastWatched
        if not last_interaction and interaction_type == "added":
            # For added items, use mtime if available
            try:
                from datetime import datetime

                if item.item.mtime:
                    last_interaction = datetime.fromisoformat(item.item.mtime.replace("Z", "+00:00"))
            except Exception:
                pass

        recency_multiplier = EvidenceCalculator.calculate_recency_multiplier(last_interaction)

        return base_weight * recency_multiplier
