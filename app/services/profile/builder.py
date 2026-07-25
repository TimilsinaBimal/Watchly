import asyncio
import math
from collections import defaultdict
from typing import Any

from loguru import logger

from app.core.constants import DEFAULT_CONCURRENCY_LIMIT, PROFILE_SCORING_VERSION
from app.models.profile import ScoredItem, TasteProfile
from app.services.profile.constants import (
    CAP_CAST,
    CAP_COUNTRY,
    CAP_DIRECTOR,
    CAP_ERA,
    CAP_GENRE,
    CAP_KEYWORD,
    CAP_RUNTIME,
    FEATURE_WEIGHT_COUNTRY,
    FEATURE_WEIGHT_CREATOR,
    FEATURE_WEIGHT_ERA,
    FEATURE_WEIGHT_GENRE,
    FEATURE_WEIGHT_KEYWORD,
    FEATURE_WEIGHT_RUNTIME,
    FREQUENCY_ENABLED,
    FREQUENCY_MULTIPLIER_BASE,
    FREQUENCY_MULTIPLIER_LOG_FACTOR,
    GENRE_MAX_POSITIONS,
    GENRE_POSITION_WEIGHTS,
    PROFILE_DECAY_ENABLED,
    PROFILE_DECAY_FACTOR,
)
from app.services.profile.evidence import EvidenceCalculator
from app.services.profile.vectorizer import ItemVectorizer


class ProfileBuilder:
    """
    Builds taste profile using additive accumulation.
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
            "runtime_buckets": defaultdict(int),
        }

        # Track weighted average for episodes (series only)
        total_weighted_episodes = 0.0
        total_weight_for_episodes = 0.0

        # Track processed items
        processed_ids = set()

        # Process all items concurrently but bounded (see _process_items_bounded).
        results = await self._process_items_bounded(scored_items, content_type)

        # First pass: accumulate scores and track frequencies
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.debug(f"Failed to process item: {result}")
                continue

            if not result:
                continue

            # Add to processed IDs
            processed_ids.add(scored_items[i].item.id)

            features, evidence_weight = result

            # Accumulate scores (pure addition)
            self._accumulate_features(profile, features, evidence_weight, feature_frequencies)

            # Track weighted episodes for average calculation (series only)
            if profile.content_type == "series" or profile.content_type is None:
                episode_count = features.get("episode_count")
                if episode_count and isinstance(episode_count, (int, float)):
                    total_weighted_episodes += float(episode_count) * evidence_weight
                    total_weight_for_episodes += evidence_weight

        # Second pass: apply frequency multipliers if enabled
        if FREQUENCY_ENABLED:
            self._apply_frequency_multipliers(profile, feature_frequencies)

        # Apply caps
        self._apply_caps(profile)

        # Calculate average episodes (series only)
        if total_weight_for_episodes > 0:
            profile.average_episodes = total_weighted_episodes / total_weight_for_episodes

        profile.processed_items = processed_ids
        profile.scoring_version = PROFILE_SCORING_VERSION

        if not profile.genre_scores and not profile.keyword_scores:
            logger.warning(
                f"Built profile for {content_type} but all scores are empty. Library may have processing issues."
            )
        return profile

    async def _process_items_bounded(self, items: list[ScoredItem], content_type: str | None) -> list[Any]:
        """Enrich items concurrently but capped at DEFAULT_CONCURRENCY_LIMIT.

        External sources (Trakt/Simkl) skip sampling and pass the user's whole
        history here, so an unbounded gather would fire 2+ TMDB calls per item at
        once. That burst overruns the connection pool / TMDB rate limit; failed
        lookups make _process_item return None and the item silently vanishes
        from the profile, so a 300-item history would build a profile from only
        the few dozen that survived. The cap mirrors the recommendation metadata
        enrichment path so all items get processed.
        """
        sem = asyncio.Semaphore(DEFAULT_CONCURRENCY_LIMIT)

        async def _guarded(item: ScoredItem) -> tuple[dict[str, Any], float] | None:
            async with sem:
                return await self._process_item(item, content_type)

        return await asyncio.gather(*[_guarded(item) for item in items], return_exceptions=True)

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

        # Calculate evidence weight (loved/liked is already baked into the weight
        # via EvidenceCalculator.weight_from_rating).
        evidence_weight = self.evidence_calculator.calculate_evidence_weight(item)
        return features, evidence_weight

    def _accumulate_features(
        self,
        profile: TasteProfile,
        features: dict[str, Any],
        evidence_weight: float,
        frequencies: dict[str, dict[Any, int]] | None = None,
    ) -> None:
        """
        Accumulate features into profile (pure addition).

        Same evidence_weight applied to all features of the item.

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
                if frequencies is not None:
                    frequencies["genres"][genre_id] += 1

        # Keywords
        keywords = features.get("keywords", [])

        for keyword_id in keywords:
            if keyword_id:
                weight = evidence_weight * FEATURE_WEIGHT_KEYWORD
                profile.keyword_scores[keyword_id] = profile.keyword_scores.get(keyword_id, 0.0) + weight
                if frequencies is not None:
                    frequencies["keywords"][keyword_id] += 1

        # Eras
        era = features.get("era")
        if era:
            weight = evidence_weight * FEATURE_WEIGHT_ERA
            profile.era_scores[era] = profile.era_scores.get(era, 0.0) + weight
            if frequencies is not None:
                frequencies["eras"][era] += 1

        # Countries
        for country_code in features.get("countries", []):
            if country_code:
                weight = evidence_weight * FEATURE_WEIGHT_COUNTRY
                profile.country_scores[country_code] = profile.country_scores.get(country_code, 0.0) + weight
                if frequencies is not None:
                    frequencies["countries"][country_code] += 1

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
                    if job in ["director", "creator"]:
                        weight = evidence_weight * FEATURE_WEIGHT_CREATOR
                        profile.director_scores[crew_id] = profile.director_scores.get(crew_id, 0.0) + weight
                        profile.director_frequency[crew_id] = profile.director_frequency.get(crew_id, 0) + 1
                        if frequencies is not None:
                            frequencies["directors"][crew_id] += 1

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
                profile.cast_frequency[cast_id] = profile.cast_frequency.get(cast_id, 0) + 1
                if frequencies is not None:
                    frequencies["cast"][cast_id] += 1

        # Runtime buckets
        runtime_bucket = features.get("runtime_bucket")
        if runtime_bucket:
            weight = evidence_weight * FEATURE_WEIGHT_RUNTIME
            current_score = profile.runtime_bucket_scores.get(runtime_bucket, 0.0)
            profile.runtime_bucket_scores[runtime_bucket] = current_score + weight
            if frequencies is not None:
                frequencies["runtime_buckets"][runtime_bucket] += 1

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

        # Runtime buckets
        for runtime_bucket, freq in frequencies["runtime_buckets"].items():
            if freq > 1:
                multiplier = FREQUENCY_MULTIPLIER_BASE + (math.log(freq) * FREQUENCY_MULTIPLIER_LOG_FACTOR)
                profile.runtime_bucket_scores[runtime_bucket] *= multiplier

    @staticmethod
    def _apply_caps(profile: TasteProfile) -> None:
        """
        Apply score caps to prevent unbounded growth (both positive and negative).
        """
        cap_pairs = [
            (profile.genre_scores, CAP_GENRE),
            (profile.keyword_scores, CAP_KEYWORD),
            (profile.director_scores, CAP_DIRECTOR),
            (profile.cast_scores, CAP_CAST),
            (profile.era_scores, CAP_ERA),
            (profile.country_scores, CAP_COUNTRY),
            (profile.runtime_bucket_scores, CAP_RUNTIME),
        ]
        for scores, cap in cap_pairs:
            for key in scores:
                scores[key] = max(-cap, min(scores[key], cap))

    async def update_profile_incrementally(
        self,
        existing_profile: TasteProfile,
        new_items: list[ScoredItem],
        content_type: str | None = None,
    ) -> TasteProfile:
        """
        Update existing profile with new items only.

        Args:
            existing_profile: Existing TasteProfile to update
            new_items: List of new ScoredItem to add
            content_type: Content type filter (movie/series) or None

        Returns:
            Updated TasteProfile
        """
        if not existing_profile:
            # No existing profile, build from scratch
            return await self.build_profile(new_items, content_type)

        # Apply gentle age decay if enabled
        if PROFILE_DECAY_ENABLED:
            self._apply_age_decay(existing_profile)

        # Process new items and accumulate features (bounded concurrency).
        results = await self._process_items_bounded(new_items, content_type)

        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.debug(f"Failed to process incremental item: {result}")
                continue

            if not result:
                continue

            # Add to processed IDs
            existing_profile.processed_items.add(new_items[i].item.id)

            features, evidence_weight = result

            self._accumulate_features(existing_profile, features, evidence_weight)

        # Apply caps to prevent unbounded growth
        self._apply_caps(existing_profile)

        return existing_profile

    def _apply_age_decay(self, profile: TasteProfile) -> None:
        """
        Apply gentle age decay to keep profile fresh.

        Args:
            profile: Profile to apply decay to
        """
        # Apply configured decay to all scores
        decay_factor = PROFILE_DECAY_FACTOR

        for score_dict in [
            profile.genre_scores,
            profile.keyword_scores,
            profile.director_scores,
            profile.cast_scores,
            profile.era_scores,
            profile.country_scores,
            profile.runtime_bucket_scores,
        ]:
            for key in score_dict:
                score_dict[key] *= decay_factor
