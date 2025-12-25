import hashlib
import math
from collections.abc import Callable
from typing import Any

from app.core.constants import DEFAULT_MINIMUM_RATING_FOR_THEME_BASED_MOVIE, DEFAULT_MINIMUM_RATING_FOR_THEME_BASED_TV


class RecommendationScoring:
    """
    Handles ranking, recency multipliers, and score normalization.
    """

    @staticmethod
    def weighted_rating(vote_avg: float | None, vote_count: int | None, C: float = 6.8, m: int = 300) -> float:
        """IMDb-style weighted rating on 0-10 scale."""
        try:
            R = float(vote_avg or 0.0)
            v = int(vote_count or 0)
        except Exception:
            R, v = 0.0, 0
        return ((v / (v + m)) * R) + ((m / (v + m)) * C)

    @staticmethod
    def normalize(value: float, min_v: float = 0.0, max_v: float = 10.0) -> float:
        """Normalize score to 0-1 range."""
        if max_v == min_v:
            return 0.0
        return max(0.0, min(1.0, (value - min_v) / (max_v - min_v)))

    @staticmethod
    def stable_epsilon(tmdb_id: int, seed: str) -> float:
        """Generate a stable tiny epsilon to break ties deterministically."""
        if not seed:
            return 0.0
        h = hashlib.md5(f"{seed}:{tmdb_id}".encode()).hexdigest()
        eps = int(h[-6:], 16) % 1000
        return eps / 1_000_000.0

    @staticmethod
    def get_recency_multiplier_fn(
        profile: Any, candidate_decades: set[int] | None = None
    ) -> tuple[Callable[[int | None], float], float]:
        """
        Build a multiplier function m(year) based on user's decade preferences.
        """
        try:
            years_map = getattr(profile.years, "values", {}) or {}
            decade_weights = {int(k): float(v) for k, v in years_map.items() if isinstance(k, int)}
            total_w = sum(decade_weights.values())
        except Exception:
            decade_weights = {}
            total_w = 0.0

        recent_w = sum(w for d, w in decade_weights.items() if d >= 2010)
        classic_w = sum(w for d, w in decade_weights.items() if d < 2000)
        total_rc = recent_w + classic_w

        if total_rc <= 0:
            return (lambda _y: 1.0), 0.0

        score = (recent_w - classic_w) / (total_rc + 1e-6)
        k = 2.0
        intensity_raw = 1.0 / (1.0 + math.exp(-k * score))
        intensity = 2.0 * (intensity_raw - 0.5)  # [-1, 1]
        alpha = abs(intensity)

        if candidate_decades:
            support = {int(d) for d in candidate_decades if isinstance(d, int)} | set(decade_weights.keys())
        else:
            support = set(decade_weights.keys())

        if not support:
            return (lambda _y: 1.0), 0.0

        if total_w > 0:
            p_user = {d: (decade_weights.get(d, 0.0) / total_w) for d in support}
        else:
            p_user = {d: 0.0 for d in support}

        D = max(1, len(support))
        uniform = 1.0 / D

        def m_raw(year: int | None) -> float:
            if year is None:
                return 1.0
            decade = (int(year) // 10) * 10
            pu = p_user.get(decade, 0.0)
            return 1.0 + intensity * (pu - uniform)

        return m_raw, alpha

    @staticmethod
    def apply_quality_adjustments(score: float, wr: float, vote_count: int, is_ranked: bool, is_fresh: bool) -> float:
        """Apply multiplicative adjustments based on item quality and source."""
        q_mult = 1.0
        if vote_count < 50:
            q_mult *= 0.6
        elif vote_count < 150:
            q_mult *= 0.85

        if wr < 5.5:
            q_mult *= 0.5
        elif wr < 6.0:
            q_mult *= 0.7
        elif wr >= 7.0 and vote_count >= 500:
            q_mult *= 1.10

        if is_ranked:
            if wr >= 6.5 and vote_count >= 200:
                q_mult *= 1.25
            elif wr >= 6.0 and vote_count >= 100:
                q_mult *= 1.10

        if is_fresh and wr >= 7.0 and vote_count >= 300:
            q_mult *= 1.10

        return score * q_mult

    @staticmethod
    def calculate_final_score(
        item: dict[str, Any],
        profile: Any,
        scorer: Any,
        mtype: str,
        is_ranked: bool = False,
        is_fresh: bool = False,
    ) -> float:  # noqa: E501
        """
        Calculate final recommendation score combining profile similarity and quality.

        Args:
            item: Item dictionary with vote_average, vote_count, etc.
            profile: User taste profile
            scorer: ProfileScorer instance
            mtype: Media type (movie/tv) to determine minimum rating
            is_ranked: Whether item is from ranked source
            is_fresh: Whether item should get freshness boost
            minimum_rating_tv: Minimum rating constant for TV
            minimum_rating_movie: Minimum rating constant for movies

        Returns:
            Final combined score (0-1 range)
        """
        # Score with profile
        profile_score = scorer.score_item(item, profile)

        # Calculate weighted rating
        C = (
            DEFAULT_MINIMUM_RATING_FOR_THEME_BASED_TV
            if mtype in ("tv", "series")
            else DEFAULT_MINIMUM_RATING_FOR_THEME_BASED_MOVIE
        )
        wr = RecommendationScoring.weighted_rating(
            item.get("vote_average"),
            item.get("vote_count"),
            C=C,
        )
        quality_score = RecommendationScoring.normalize(wr)

        # Apply quality adjustments
        vote_count = item.get("vote_count", 0)
        adjusted_profile_score = RecommendationScoring.apply_quality_adjustments(
            profile_score, wr, vote_count, is_ranked=is_ranked, is_fresh=is_fresh
        )

        # Combined score: profile similarity (with quality adjustments) + quality
        final_score = (adjusted_profile_score * 0.6) + (quality_score * 0.4)

        return final_score
