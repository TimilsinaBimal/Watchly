import asyncio
import math
from collections import defaultdict
from typing import Any

from loguru import logger

from app.models.scoring import ScoredItem
from app.models.taste_profile import TasteProfile
from app.services.profile.constants import (
    CAP_CAST,
    CAP_COUNTRY,
    CAP_DIRECTOR,
    CAP_ERA,
    CAP_GENRE,
    CAP_KEYWORD,
    CREW_JOB_DIRECTOR,
    CREW_JOB_OTHER,
    FEATURE_WEIGHT_COUNTRY,
    FEATURE_WEIGHT_CREATOR,
    FEATURE_WEIGHT_ERA,
    FEATURE_WEIGHT_GENRE,
    FEATURE_WEIGHT_KEYWORD,
    FREQUENCY_ENABLED,
    FREQUENCY_MULTIPLIER_BASE,
    FREQUENCY_MULTIPLIER_LOG_FACTOR,
    GENRE_MAX_POSITIONS,
    GENRE_POSITION_WEIGHTS,
)
from app.services.profile.evidence import EvidenceCalculator
from app.services.profile.vectorizer import ItemVectorizer


class ProfileBuilder:
    """
    Builds taste profile using additive accumulation.

    Design principles:
    - Pure accumulation: score += weight (no conditionals)
    - Same weight to all metadata of an item
    - No normalization at write time
    - Easy to debug: print(profile.genre_scores)
    """

    def __init__(self, vectorizer: ItemVectorizer):
        """
        Initialize profile builder.

        Args:
            vectorizer: ItemVectorizer for extracting features
        """
        self.vectorizer = vectorizer
        self.evidence_calculator = EvidenceCalculator()

    async def build_profile(self, scored_items: list[ScoredItem], content_type: str | None = None) -> TasteProfile:
        """
        Build taste profile from scored items.

        Args:
            scored_items: List of scored items to process
            content_type: Filter by content type (movie/series) or None for all

        Returns:
            Built TasteProfile
        """
        # Initialize profile
        profile = TasteProfile(content_type=content_type)

        # Track frequencies for optional frequency multiplier
        feature_frequencies: dict[str, dict[Any, int]] = {
            "genres": defaultdict(int),
            "keywords": defaultdict(int),
            "eras": defaultdict(int),
            "countries": defaultdict(int),
            "directors": defaultdict(int),
            "cast": defaultdict(int),
        }

        # Process all items in parallel
        tasks = [self._process_item(item, content_type) for item in scored_items]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # First pass: accumulate scores and track frequencies
        for result in results:
            if isinstance(result, Exception):
                logger.debug(f"Failed to process item: {result}")
                continue

            if not result:
                continue

            features, evidence_weight = result

            # Accumulate scores (pure addition)
            self._accumulate_features(profile, features, evidence_weight, feature_frequencies)

        # Second pass: apply frequency multipliers if enabled
        if FREQUENCY_ENABLED:
            self._apply_frequency_multipliers(profile, feature_frequencies)

        # Apply caps
        self._apply_caps(profile)

        return profile

    async def _process_item(self, item: ScoredItem, content_type: str | None) -> tuple[dict[str, Any], float] | None:
        """
        Process a single item and extract features.

        Args:
            item: ScoredItem to process
            content_type: Filter by content type

        Returns:
            Tuple of (features_dict, evidence_weight) or None
        """
        # Filter by content type
        if content_type and item.item.type != content_type:
            return None

        # Extract features
        features = await self.vectorizer.extract_features(item)
        if not features:
            return None

        # Calculate evidence weight
        evidence_weight = self.evidence_calculator.calculate_evidence_weight(item)

        return features, evidence_weight

    def _accumulate_features(
        self,
        profile: TasteProfile,
        features: dict[str, Any],
        evidence_weight: float,
        frequencies: dict[str, dict[Any, int]],
    ) -> None:
        """
        Accumulate features into profile (pure addition).

        Same evidence_weight applied to all features of the item.
        No conditionals, no derived features.

        Args:
            profile: Profile to update
            features: Extracted features
            evidence_weight: Weight for this item
            frequencies: Frequency tracker for optional multipliers
        """
        # Genres (with position-based decay - only top 3)
        genres = features.get("genres", [])[:GENRE_MAX_POSITIONS]
        for idx, genre_id in enumerate(genres):
            if genre_id:
                # Apply position weight (first=1.0, second=0.6, third=0.3)
                position_weight = GENRE_POSITION_WEIGHTS[idx] if idx < len(GENRE_POSITION_WEIGHTS) else 0.1
                weight = evidence_weight * FEATURE_WEIGHT_GENRE * position_weight
                profile.genre_scores[genre_id] = profile.genre_scores.get(genre_id, 0.0) + weight
                frequencies["genres"][genre_id] += 1

        # Keywords
        for keyword_id in features.get("keywords", []):
            if keyword_id:
                weight = evidence_weight * FEATURE_WEIGHT_KEYWORD
                profile.keyword_scores[keyword_id] = profile.keyword_scores.get(keyword_id, 0.0) + weight
                frequencies["keywords"][keyword_id] += 1

        # Eras
        era = features.get("era")
        if era:
            weight = evidence_weight * FEATURE_WEIGHT_ERA
            profile.era_scores[era] = profile.era_scores.get(era, 0.0) + weight
            frequencies["eras"][era] += 1

        # Countries
        for country_code in features.get("countries", []):
            if country_code:
                weight = evidence_weight * FEATURE_WEIGHT_COUNTRY
                profile.country_scores[country_code] = profile.country_scores.get(country_code, 0.0) + weight
                frequencies["countries"][country_code] += 1

        # Directors (with job-based weights)
        crew_list = features.get("crew", [])
        if isinstance(crew_list, list):
            for crew_item in crew_list:
                if isinstance(crew_item, dict):
                    crew_id = crew_item.get("id")
                    job = crew_item.get("job", "").lower()
                else:
                    crew_id = crew_item
                    job = ""

                if crew_id:
                    # Director gets full weight, others get 0.5
                    job_weight = CREW_JOB_DIRECTOR if job == "director" else CREW_JOB_OTHER
                    weight = evidence_weight * FEATURE_WEIGHT_CREATOR * job_weight
                    profile.director_scores[crew_id] = profile.director_scores.get(crew_id, 0.0) + weight
                    frequencies["directors"][crew_id] += 1

        # Cast (with position weights - already calculated in vectorizer)
        for cast_item in features.get("cast", []):
            if isinstance(cast_item, dict):
                cast_id = cast_item.get("id")
                position_weight = cast_item.get("weight", 1.0)
            else:
                cast_id = cast_item
                position_weight = 1.0

            if cast_id:
                weight = evidence_weight * FEATURE_WEIGHT_CREATOR * position_weight
                profile.cast_scores[cast_id] = profile.cast_scores.get(cast_id, 0.0) + weight
                frequencies["cast"][cast_id] += 1

    def _apply_frequency_multipliers(self, profile: TasteProfile, frequencies: dict[str, dict[Any, int]]) -> None:
        """
        Apply optional frequency multipliers (subtle boost for repeated patterns).

        Args:
            profile: Profile to update
            frequencies: Frequency counts per feature
        """
        # Genres
        for genre_id, freq in frequencies["genres"].items():
            if freq > 1:
                multiplier = FREQUENCY_MULTIPLIER_BASE + (math.log(freq) * FREQUENCY_MULTIPLIER_LOG_FACTOR)
                profile.genre_scores[genre_id] *= multiplier

        # Keywords
        for keyword_id, freq in frequencies["keywords"].items():
            if freq > 1:
                multiplier = FREQUENCY_MULTIPLIER_BASE + (math.log(freq) * FREQUENCY_MULTIPLIER_LOG_FACTOR)
                profile.keyword_scores[keyword_id] *= multiplier

        # Directors
        for director_id, freq in frequencies["directors"].items():
            if freq > 1:
                multiplier = FREQUENCY_MULTIPLIER_BASE + (math.log(freq) * FREQUENCY_MULTIPLIER_LOG_FACTOR)
                profile.director_scores[director_id] *= multiplier

        # Cast
        for cast_id, freq in frequencies["cast"].items():
            if freq > 1:
                multiplier = FREQUENCY_MULTIPLIER_BASE + (math.log(freq) * FREQUENCY_MULTIPLIER_LOG_FACTOR)
                profile.cast_scores[cast_id] *= multiplier

    @staticmethod
    def _apply_caps(profile: TasteProfile) -> None:
        """
        Apply score caps to prevent unbounded growth.

        Args:
            profile: Profile to cap
        """
        # Cap genres
        for genre_id in profile.genre_scores:
            profile.genre_scores[genre_id] = min(profile.genre_scores[genre_id], CAP_GENRE)

        # Cap keywords
        for keyword_id in profile.keyword_scores:
            profile.keyword_scores[keyword_id] = min(profile.keyword_scores[keyword_id], CAP_KEYWORD)

        # Cap directors
        for director_id in profile.director_scores:
            profile.director_scores[director_id] = min(profile.director_scores[director_id], CAP_DIRECTOR)

        # Cap cast
        for cast_id in profile.cast_scores:
            profile.cast_scores[cast_id] = min(profile.cast_scores[cast_id], CAP_CAST)

        # Cap eras
        for era in profile.era_scores:
            profile.era_scores[era] = min(profile.era_scores[era], CAP_ERA)

        # Cap countries
        for country in profile.country_scores:
            profile.country_scores[country] = min(profile.country_scores[country], CAP_COUNTRY)
