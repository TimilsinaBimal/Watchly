from datetime import datetime, timezone

from app.models.scoring import ScoredItem, StremioLibraryItem


class ScoringService:
    """
    Service for calculating user interest scores for library items.
    It consumes raw dictionary data or Pydantic models and returns enriched ScoredItems.
    """

    # TODO: Make this a bit more complex based on more parameters.
    # Rewatch, How many times? Watched but duration?? What if user stopped watching in middle?

    # Weights for different factors
    WEIGHT_WATCH_PERCENTAGE = 0.10
    WEIGHT_REWATCH = 0.17
    WEIGHT_RECENCY = 0.30
    WEIGHT_EXPLICIT_RATING = 0.35
    ADDED_TO_LIBRARY_WEIGHT = 0.08

    def process_item(self, raw_item: dict) -> ScoredItem:
        """
        Process a raw Stremio item dictionary into a ScoredItem.
        """
        # Convert dict to Pydantic model for validation and typing
        item = StremioLibraryItem(**raw_item)

        score_data = self._calculate_score_components(item)

        return ScoredItem(
            item=item,
            score=score_data["final_score"],
            completion_rate=score_data["completion_rate"],
            is_rewatched=score_data["is_rewatched"],
            is_recent=score_data["is_recent"],
            source_type="loved" if item.is_loved else ("liked" if item.is_liked else "watched"),
        )

    def calculate_score(self, item: dict | StremioLibraryItem, is_loved: bool = False, is_liked: bool = False) -> float:
        """
        Backwards compatible method to just get the float score.
        Accepts either a raw dict or a StremioLibraryItem.
        """
        if isinstance(item, dict):
            # Temporarily inject flags if passed separately (legacy support)
            if "_is_loved" not in item:
                item["_is_loved"] = is_loved
            if "_is_liked" not in item:
                item["_is_liked"] = is_liked
            model_item = StremioLibraryItem(**item)
        else:
            model_item = item

        return self._calculate_score_components(model_item)["final_score"]

    def _calculate_score_components(self, item: StremioLibraryItem) -> dict:
        """Internal logic to calculate score components."""
        state = item.state

        # 1. Completion Score
        completion_score = 0.0
        completion_rate = 0.0

        # Prefer ratio-based completion when duration is available to avoid
        # treating short partial plays as full completion just because
        # `timesWatched` was incremented. If duration is missing, fall back
        # to conservative estimates based on timesWatched/flaggedWatched.
        if state.duration and state.duration > 0:
            try:
                ratio = min(float(state.timeWatched) / float(state.duration), 1.0)
            except Exception:
                ratio = 0.0
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

        # 2. Rewatch Bonus
        # We compute rewatch strength using two complementary metrics:
        #  - times_based: how many extra explicit watches the user has (timesWatched - 1)
        #  - ratio_based: overallTimeWatched / duration measures how many full-length equivalents
        # If duration is missing we fall back to conservative estimators to avoid false positives.
        rewatch_score = 0.0
        is_rewatched = False
        if state.timesWatched > 1 and not state.flaggedWatched:
            is_rewatched = True

            # times-based component (each extra watch gives a boost)
            times_component = (state.timesWatched - 1) * 50

            # ratio-based component: how many full durations the user has watched in total
            ratio_component = 0.0
            try:
                overall_timewatched = float(state.overallTimeWatched or 0)
                duration = float(state.duration or 0)
                if duration > 0 and overall_timewatched > 0:
                    watch_ratio = overall_timewatched / duration
                    ratio_component = max((watch_ratio - 1.0) * 100.0, 0.0)
                else:
                    # If duration is missing, be conservative: estimate based on timeWatched
                    # If timeWatched exists, assume it approximates one viewing; otherwise use timesWatched
                    time_watched = float(state.timeWatched or 0)
                    if time_watched > 0:
                        # assume a single-view baseline equal to time_watched, so overall/time_watched ~= times
                        ratio_est = (
                            overall_timewatched / time_watched if time_watched > 0 else float(state.timesWatched)
                        )
                        ratio_component = max((ratio_est - 1.0) * 100.0, 0.0)
                    else:
                        ratio_component = max((float(state.timesWatched) - 1.0) * 20.0, 0.0)
            except Exception:
                ratio_component = 0.0

            # Combine components but clamp to reasonable bounds
            combined = max(times_component, ratio_component)
            rewatch_score = min(combined, 100.0)

        # 3. Recency Score
        recency_score = 0.0
        is_recent = False
        if state.lastWatched:
            now = datetime.now(timezone.utc)
            # Ensure timezone awareness
            last_watched = state.lastWatched
            if last_watched.tzinfo is None:
                last_watched = last_watched.replace(tzinfo=timezone.utc)

            days_since = (now - last_watched).days

            if days_since < 7:
                recency_score = 200
                is_recent = True
            elif days_since < 30:
                recency_score = 100
                is_recent = True
            elif days_since < 90:
                recency_score = 70
            elif days_since < 180:
                recency_score = 30
            elif days_since < 365:
                recency_score = 10

        # 4. Explicit Rating Score
        rating_score = 0.0
        if item.is_loved:
            rating_score = 100.0
        elif item.is_liked:
            rating_score = 70.0

        # 5. Added to Library Score
        added_to_library_score = 0.0
        if not item.temp and not item.removed:
            added_to_library_score = 100.0
        # if item.removed:
        #     # should we penalize for removed items?
        #     added_to_library_score = -50.0

        # Calculate Final Score
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
            "is_rewatched": is_rewatched,
            "is_recent": is_recent,
        }
