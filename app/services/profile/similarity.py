from typing import Any

from app.models.profile import UserTasteProfile
from app.services.profile.vectorizer import ProfileVectorizer

# Weights for different dimensions
GENRES_WEIGHT = 0.20
KEYWORDS_WEIGHT = 0.30
CAST_WEIGHT = 0.12
CREW_WEIGHT = 0.08
YEAR_WEIGHT = 0.05
COUNTRIES_WEIGHT = 0.05
TOPICS_WEIGHT = 0.20


def jaccard_similarity(set_a: set[Any], set_b: set[Any]) -> float:
    """Calculate Jaccard similarity between two sets."""
    if not set_a and not set_b:
        return 0.0
    if not set_a or not set_b:
        return 0.0

    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union > 0 else 0.0


def calculate_similarity_breakdown(
    profile: UserTasteProfile, item_meta: dict[str, Any]
) -> tuple[float, dict[str, float]]:
    """
    Calculate similarity between a user profile and an item,
    returning both the total score and a dimensional breakdown.
    """
    item_vec = ProfileVectorizer.vectorize_item(item_meta)

    def avg_feature_preference(features: list[Any], weight_map: dict[Any, float]) -> float:
        if not features:
            return 0.0
        total_pref = sum(weight_map.get(f, 0.0) for f in features)
        return total_pref / max(1, len(features))

    # Calculate scores per dimension
    g_score = avg_feature_preference(item_vec.get("genres", []), profile.genres.values) * GENRES_WEIGHT
    k_score = avg_feature_preference(item_vec.get("keywords", []), profile.keywords.values) * KEYWORDS_WEIGHT
    c_score = avg_feature_preference(item_vec.get("cast", []), profile.cast.values) * CAST_WEIGHT
    t_score = avg_feature_preference(item_vec.get("topics", []), profile.topics.values) * TOPICS_WEIGHT
    crew_score = avg_feature_preference(item_vec.get("crew", []), profile.crew.values) * CREW_WEIGHT
    country_score = avg_feature_preference(item_vec.get("countries", []), profile.countries.values) * COUNTRIES_WEIGHT

    year_val = item_vec.get("year")
    year_score = 0.0
    if year_val is not None:
        year_score = profile.years.values.get(year_val, 0.0) * YEAR_WEIGHT

    total_score = g_score + k_score + c_score + t_score + crew_score + country_score + year_score

    breakdown = {
        "genres": float(g_score),
        "keywords": float(k_score),
        "cast": float(c_score),
        "topics": float(t_score),
        "crew": float(crew_score),
        "countries": float(country_score),
        "year": float(year_score),
        "total": float(total_score),
    }

    return float(total_score), breakdown


def calculate_simple_overlap_breakdown(
    profile: UserTasteProfile,
    item_meta: dict[str, Any],
    top_topic_tokens: int = 300,
    top_genres: int = 20,
    top_keyword_ids: int = 200,
) -> tuple[float, dict[str, float]]:
    """
    Calculate similarity using simple set overlaps (Jaccard).
    """
    # Item sets
    item_vec = ProfileVectorizer.vectorize_item(item_meta)
    item_topic_tokens = set(item_vec.get("topics") or [])
    item_genres = {int(g) for g in (item_vec.get("genres") or [])}
    item_keyword_ids = {int(k) for k in (item_vec.get("keywords") or [])}

    # Helper to get top features from profile
    def get_top_features(weight_map: dict[Any, float], limit: int) -> set[Any]:
        sorted_features = sorted(weight_map.items(), key=lambda x: x[1], reverse=True)
        return {k for k, _ in sorted_features[:limit]}

    # Profile preference sets
    pref_topic_tokens = get_top_features(profile.topics.values, top_topic_tokens)
    pref_genres = {int(g) for g in get_top_features(profile.genres.values, top_genres)}
    pref_keyword_ids = {int(k) for k in get_top_features(profile.keywords.values, top_keyword_ids)}

    # Jaccard similarities
    topics_j = jaccard_similarity(item_topic_tokens, pref_topic_tokens)
    genres_j = jaccard_similarity(item_genres, pref_genres)
    kw_j = jaccard_similarity(item_keyword_ids, pref_keyword_ids)

    # Weighted sum
    w_topics, w_genres, w_kw = 0.6, 0.25, 0.15
    total_score = (topics_j * w_topics) + (genres_j * w_genres) + (kw_j * w_kw)

    breakdown = {
        "topics_jaccard": float(topics_j),
        "genres_jaccard": float(genres_j),
        "keywords_jaccard": float(kw_j),
        "total": float(total_score),
    }

    return float(total_score), breakdown
