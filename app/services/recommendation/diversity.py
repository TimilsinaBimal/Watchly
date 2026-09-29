from collections import defaultdict
from typing import Any

from app.services.profile.constants import TOP_PICKS_GENRE_CAP
from app.services.recommendation.filtering import RecommendationFiltering
from app.services.recommendation.scoring import RecommendationScoring


def apply_diversity_caps(
    scored_candidates: list[tuple[float, dict[str, Any]]],
    limit: int,
    mtype: str,
    user_settings: Any = None,
) -> list[dict[str, Any]]:
    """
    Apply diversity caps to ensure balanced results.

    Caps:
    - Genre: max 50% per genre
    - Quality: minimum vote_count and rating
    """
    result = []
    genre_counts: dict[int, int] = defaultdict(int)

    max_per_genre = int(limit * TOP_PICKS_GENRE_CAP)

    for score, item in scored_candidates:
        if len(result) >= limit:
            break

        item_id = item.get("id")
        if not item_id:
            continue

        # Quality threshold
        vote_count = item.get("vote_count", 0)
        vote_avg = item.get("vote_average", 0)

        min_rating, min_votes = RecommendationFiltering.get_quality_thresholds(user_settings)

        if vote_count < min_votes:
            continue

        wr = RecommendationScoring.weighted_rating(vote_avg, vote_count, C=7.2 if mtype == "tv" else 6.8)
        if wr < min_rating:
            continue

        # Check genre cap (50% max per genre)
        genre_ids = item.get("genre_ids", [])
        top_genre = genre_ids[0] if genre_ids else None

        if top_genre:
            if genre_counts[top_genre] >= max_per_genre:
                continue

        result.append(item)

        if top_genre:
            genre_counts[top_genre] += 1

    return result
