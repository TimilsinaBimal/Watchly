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
    WEIGHT_WATCH_PERCENTAGE = 0.25
    WEIGHT_REWATCH = 0.20
    WEIGHT_RECENCY = 0.20
    WEIGHT_EXPLICIT_RATING = 0.3
    ADDED_TO_LIBRARY_WEIGHT = 0.05

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

    def calculate_score(
        self, item: dict | StremioLibraryItem, is_loved: bool = False, is_liked: bool = False
    ) -> float:
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

        if state.duration > 0:
            ratio = min(state.timeWatched / state.duration, 1.0)
            completion_score = ratio * 100
            completion_rate = ratio
        elif state.timesWatched > 0 or state.flaggedWatched > 0:
            completion_score = 100.0
            completion_rate = 1.0

        # 2. Rewatch Bonus
        rewatch_score = 0.0
        is_rewatched = False
        if state.timesWatched > 1:
            rewatch_score = min((state.timesWatched - 1) * 50, 100)
            is_rewatched = True

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
                recency_score = 150
                is_recent = True
            elif days_since < 30:
                recency_score = 100
                is_recent = True
            elif days_since < 90:
                recency_score = 70
            elif days_since < 180:
                recency_score = 40
            elif days_since < 365:
                recency_score = 20

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
