import math
from datetime import datetime, timezone

from app.models.library import StremioLibraryItem
from app.models.profile import ScoredItem


class ScoringService:
    """Calculates user interest scores for library items."""

    WEIGHT_WATCH_PERCENTAGE = 0.10
    WEIGHT_REWATCH = 0.17
    WEIGHT_RECENCY = 0.30
    WEIGHT_EXPLICIT_RATING = 0.35
    ADDED_TO_LIBRARY_WEIGHT = 0.08

    def process_item(self, item: StremioLibraryItem) -> ScoredItem:
        score_data = self._calculate_score_components(item)

        return ScoredItem(
            item=item,
            score=score_data["final_score"],
            completion_rate=score_data["completion_rate"],
            source_type="loved" if item.is_loved else ("liked" if item.is_liked else "watched"),
        )

    def _calculate_score_components(self, item: StremioLibraryItem) -> dict:
        state = item.state

        completion_score = 0.0
        completion_rate = 0.0

        if state.duration > 0:
            ratio = min(state.timeWatched / state.duration, 1.0)
            completion_rate = ratio
            completion_score = ratio * 100.0

            # If the item was explicitly marked watched or has timesWatched but
            # the observed ratio is very small, give a modest boost (not full 100).
            if (state.timesWatched > 0 or state.flaggedWatched > 0) and completion_score < 50.0:
                completion_score = max(completion_score, 50.0)
                completion_rate = max(completion_rate, 0.5)
        elif state.timesWatched > 0 or state.flaggedWatched > 0:
            # No duration information: use a conservative assumed completion.
            completion_score = 80.0
            completion_rate = 0.8

        # Rewatch bonus. We compute rewatch strength using two complementary metrics:
        #  - times_based: how many extra explicit watches the user has (timesWatched - 1)
        #  - ratio_based: overallTimeWatched / duration measures how many full-length equivalents
        # If duration is missing we fall back to conservative estimators to avoid false positives.
        rewatch_score = 0.0
        if state.timesWatched > 1 and not state.flaggedWatched:
            # times-based component (each extra watch gives a boost)
            times_component = (state.timesWatched - 1) * 50

            # ratio-based component: how many full durations the user has watched in total
            if state.duration > 0 and state.overallTimeWatched > 0:
                watch_ratio = state.overallTimeWatched / state.duration
                ratio_component = max((watch_ratio - 1.0) * 100.0, 0.0)
            elif state.timeWatched > 0:
                # Without a duration, take timeWatched as one viewing, so
                # overall/timeWatched approximates the number of viewings.
                ratio_est = state.overallTimeWatched / state.timeWatched
                ratio_component = max((ratio_est - 1.0) * 100.0, 0.0)
            else:
                ratio_component = max((state.timesWatched - 1.0) * 20.0, 0.0)

            # Combine components but clamp to reasonable bounds
            combined = max(times_component, ratio_component)
            rewatch_score = min(combined, 100.0)

        # Recency: exponential decay
        recency_score = 0.0
        if state.lastWatched:
            now = datetime.now(timezone.utc)
            last_watched = state.lastWatched
            if last_watched.tzinfo is None:
                last_watched = last_watched.replace(tzinfo=timezone.utc)

            days_since = max((now - last_watched).days, 0)

            MAX_RECENCY_SCORE = 100.0
            HALF_LIFE_DAYS = 60.0  # Days for score to halve

            recency_score = MAX_RECENCY_SCORE * math.exp(-days_since / HALF_LIFE_DAYS)

        rating_score = 0.0
        if item.is_loved:
            rating_score = 100.0
        elif item.is_liked:
            rating_score = 70.0

        added_to_library_score = 0.0
        if not item.temp and not item.removed:
            added_to_library_score = 100.0

        final_score = (
            (completion_score * self.WEIGHT_WATCH_PERCENTAGE)
            + (rewatch_score * self.WEIGHT_REWATCH)
            + (recency_score * self.WEIGHT_RECENCY)
            + (rating_score * self.WEIGHT_EXPLICIT_RATING)
            + (added_to_library_score * self.ADDED_TO_LIBRARY_WEIGHT)
        )

        return {
            "final_score": min(max(final_score, 0), 100),
            "completion_rate": completion_rate,
        }
