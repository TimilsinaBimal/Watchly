from collections import defaultdict
from datetime import datetime
from typing import Any

from app.services.profile.constants import TOP_PICKS_CREATOR_CAP, TOP_PICKS_GENRE_CAP
from app.services.recommendation.filtering import RecommendationFiltering
from app.services.recommendation.scoring import RecommendationScoring


def extract_year(item: dict[str, Any]) -> int | None:
    """Extract year from item."""
    release_date = item.get("release_date") or item.get("first_air_date")
    if release_date:
        try:
            return int(str(release_date)[:4])
        except (ValueError, TypeError):
            pass
    return None


def is_recent_release(item: dict[str, Any], threshold: datetime, mtype: str) -> bool:
    """Check if item was released within the threshold (e.g., last 3 months)."""
    release_date_str = item.get("release_date") if mtype == "movie" else item.get("first_air_date")
    if not release_date_str:
        return False

    try:
        release_date = datetime.strptime(str(release_date_str)[:10], "%Y-%m-%d")
        return release_date >= threshold
    except (ValueError, TypeError):
        return False


def year_to_era(year: int) -> str:
    """Convert year to era bucket."""
    if year < 1970:
        return "pre-1970s"
    elif year < 1980:
        return "1970s"
    elif year < 1990:
        return "1990s"
    elif year < 2000:
        return "2000s"
    elif year < 2010:
        return "2010s"
    elif year < 2020:
        return "2020s"
    else:
        return "2020s"


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


def apply_creator_cap(items: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """
    Apply creator cap (max 2 items per director/actor) after enrichment.
    """
    result = []
    creator_counts: dict[int, int] = defaultdict(int)

    for item in items:
        if len(result) >= limit:
            break

        credits = item.get("credits", {}) or {}
        crew = credits.get("crew", []) or []
        cast = credits.get("cast", []) or []

        # Check director cap
        directors = [c.get("id") for c in crew if c.get("job", "").lower() == "director" and c.get("id")]
        blocked_by_director = False
        for dir_id in directors:
            if creator_counts[dir_id] >= TOP_PICKS_CREATOR_CAP:
                blocked_by_director = True
                break

        # Check cast cap (top 3 only)
        top_cast = [c.get("id") for c in cast[:3] if c.get("id")]
        blocked_by_cast = False
        for cast_id in top_cast:
            if creator_counts[cast_id] >= TOP_PICKS_CREATOR_CAP:
                blocked_by_cast = True
                break

        if blocked_by_director or blocked_by_cast:
            continue

        result.append(item)

        for dir_id in directors:
            creator_counts[dir_id] += 1
        for cast_id in top_cast:
            creator_counts[cast_id] += 1

    return result
