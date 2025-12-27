from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class TasteProfile(BaseModel):
    """
    Transparent, additive taste profile.

    Answers one question: "Which item is more likely to be liked by this user?"

    All scores are additive accumulations. No normalization at write time.
    Normalization happens only at read time for ranking.
    """

    # Core feature scores (additive accumulation)
    genre_scores: dict[int, float] = Field(default_factory=dict, description="Genre ID → accumulated score")
    keyword_scores: dict[int, float] = Field(default_factory=dict, description="Keyword ID → accumulated score")
    era_scores: dict[str, float] = Field(
        default_factory=dict, description="Era bucket (e.g., '1990s', '2010s') → score"
    )
    country_scores: dict[str, float] = Field(default_factory=dict, description="Country code → accumulated score")
    director_scores: dict[int, float] = Field(default_factory=dict, description="Director ID → accumulated score")
    cast_scores: dict[int, float] = Field(default_factory=dict, description="Actor ID → accumulated score")

    # Metadata
    last_updated: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    content_type: str | None = Field(default=None, description="movie or series")

    class Config:
        """Pydantic configuration."""

        json_encoders = {datetime: lambda v: v.isoformat()}

    def get_top_genres(self, limit: int = 5) -> list[tuple[int, float]]:
        """Get top N genres by score."""
        return sorted(self.genre_scores.items(), key=lambda x: x[1], reverse=True)[:limit]

    def get_top_keywords(self, limit: int = 5) -> list[tuple[int, float]]:
        """Get top N keywords by score."""
        return sorted(self.keyword_scores.items(), key=lambda x: x[1], reverse=True)[:limit]

    def get_top_eras(self, limit: int = 3) -> list[tuple[str, float]]:
        """Get top N eras by score."""
        return sorted(self.era_scores.items(), key=lambda x: x[1], reverse=True)[:limit]

    def get_top_countries(self, limit: int = 3) -> list[tuple[str, float]]:
        """Get top N countries by score."""
        return sorted(self.country_scores.items(), key=lambda x: x[1], reverse=True)[:limit]

    def get_top_directors(self, limit: int = 5) -> list[tuple[int, float]]:
        """Get top N directors by score."""
        return sorted(self.director_scores.items(), key=lambda x: x[1], reverse=True)[:limit]

    def get_top_cast(self, limit: int = 5) -> list[tuple[int, float]]:
        """Get top N cast members by score."""
        return sorted(self.cast_scores.items(), key=lambda x: x[1], reverse=True)[:limit]

    def get_top_creators(self, limit: int = 5) -> list[tuple[int, float]]:
        """
        Get top N creators (directors + cast merged) by score.

        Runtime merge for convenience. Profile stores them separately.
        """
        # Merge directors and cast for combined ranking
        all_creators = {**self.director_scores, **self.cast_scores}
        return sorted(all_creators.items(), key=lambda x: x[1], reverse=True)[:limit]

    def normalize_for_ranking(self) -> dict[str, dict[Any, float]]:
        """
        Normalize scores for ranking (read-time only).

        Returns normalized scores (0-1 range) for each feature type.
        Used only when generating recommendations, never during profile updates.
        """

        def normalize_dict(scores: dict[Any, float]) -> dict[Any, float]:
            if not scores:
                return {}
            max_score = max(scores.values()) if scores.values() else 1.0
            if max_score <= 0:
                return scores
            return {k: v / max_score for k, v in scores.items()}

        return {
            "genres": normalize_dict(self.genre_scores),
            "keywords": normalize_dict(self.keyword_scores),
            "eras": normalize_dict(self.era_scores),
            "countries": normalize_dict(self.country_scores),
            "directors": normalize_dict(self.director_scores),
            "cast": normalize_dict(self.cast_scores),
            "creators": normalize_dict({**self.director_scores, **self.cast_scores}),
        }
