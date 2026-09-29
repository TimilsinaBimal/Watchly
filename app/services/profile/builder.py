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
    FREQUENCY_MULTIPLIER_LOG_FACTOR,
    GENRE_MAX_POSITIONS,
    GENRE_POSITION_WEIGHTS,
    PROFILE_DECAY_FACTOR,
)
from app.services.profile.evidence import EvidenceCalculator
from app.services.profile.vectorizer import ItemVectorizer


class ProfileBuilder:
    """Builds taste profile using additive accumulation."""

    def __init__(self, vectorizer: ItemVectorizer):
        self.vectorizer = vectorizer
        self.evidence_calculator = EvidenceCalculator()

    async def build_profile(self, scored_items: list[ScoredItem], content_type: str) -> TasteProfile:
        profile = TasteProfile(content_type=content_type)

        feature_frequencies: dict[str, dict[Any, int]] = {
            "genres": defaultdict(int),
            "keywords": defaultdict(int),
            "eras": defaultdict(int),
            "countries": defaultdict(int),
            "directors": defaultdict(int),
            "cast": defaultdict(int),
            "runtime_buckets": defaultdict(int),
        }

        processed_ids = set()

        results = await self._process_items_bounded(scored_items, content_type)

        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.debug(f"Failed to process item: {result}")
                continue

            if not result:
                continue

            processed_ids.add(scored_items[i].item.id)

            features, evidence_weight = result

            self._accumulate_features(profile, features, evidence_weight, feature_frequencies)

        self._apply_frequency_multipliers(profile, feature_frequencies)
        self._apply_caps(profile)

        profile.processed_items = processed_ids
        profile.scoring_version = PROFILE_SCORING_VERSION

        # Items whose TMDB lookup failed contribute nothing and drop out silently,
        # so say how many made it in. A large gap here means the profile is thinner
        # than the library suggests, which looks like bad recommendations rather
        # than like an API problem.
        dropped = len(scored_items) - len(processed_ids)
        if dropped:
            logger.warning(
                f"Built {content_type} profile from {len(processed_ids)}/{len(scored_items)} items "
                f"({dropped} dropped, most likely failed TMDB lookups)"
            )
        else:
            logger.info(f"Built {content_type} profile from all {len(processed_ids)} items")

        if not profile.genre_scores and not profile.keyword_scores:
            logger.warning(
                f"Built profile for {content_type} but all scores are empty. Library may have processing issues."
            )
        return profile

    async def _process_items_bounded(self, items: list[ScoredItem], content_type: str) -> list[Any]:
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

    async def _process_item(self, item: ScoredItem, content_type: str) -> tuple[dict[str, Any], float] | None:
        if item.item.type != content_type:
            return None

        features = await self.vectorizer.extract_features(item)
        if not features:
            return None

        # Loved/liked is already baked into the evidence weight.
        evidence_weight = self.evidence_calculator.calculate_evidence_weight(item)
        return features, evidence_weight

    def _accumulate_features(
        self,
        profile: TasteProfile,
        features: dict[str, Any],
        evidence_weight: float,
        frequencies: dict[str, dict[Any, int]] | None = None,
    ) -> None:
        """Add one item's features to the profile, all at the item's evidence weight."""
        # A title's first genres describe it best, so only the top few count, each
        # at a decaying position weight.
        genres = features.get("genres", [])[:GENRE_MAX_POSITIONS]
        for idx, genre_id in enumerate(genres):
            if genre_id:
                position_weight = GENRE_POSITION_WEIGHTS[idx]
                weight = evidence_weight * FEATURE_WEIGHT_GENRE * position_weight
                profile.genre_scores[genre_id] = profile.genre_scores.get(genre_id, 0.0) + weight
                if frequencies is not None:
                    frequencies["genres"][genre_id] += 1

        for keyword_id in features.get("keywords", []):
            if keyword_id:
                weight = evidence_weight * FEATURE_WEIGHT_KEYWORD
                profile.keyword_scores[keyword_id] = profile.keyword_scores.get(keyword_id, 0.0) + weight
                if frequencies is not None:
                    frequencies["keywords"][keyword_id] += 1

        era = features.get("era")
        if era:
            weight = evidence_weight * FEATURE_WEIGHT_ERA
            profile.era_scores[era] = profile.era_scores.get(era, 0.0) + weight
            if frequencies is not None:
                frequencies["eras"][era] += 1

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

        runtime_bucket = features.get("runtime_bucket")
        if runtime_bucket:
            weight = evidence_weight * FEATURE_WEIGHT_RUNTIME
            current_score = profile.runtime_bucket_scores.get(runtime_bucket, 0.0)
            profile.runtime_bucket_scores[runtime_bucket] = current_score + weight
            if frequencies is not None:
                frequencies["runtime_buckets"][runtime_bucket] += 1

    def _apply_frequency_multipliers(self, profile: TasteProfile, frequencies: dict[str, dict[Any, int]]) -> None:
        """Subtle boost for features that recur across items."""
        for scores, counts in (
            (profile.genre_scores, frequencies["genres"]),
            (profile.keyword_scores, frequencies["keywords"]),
            (profile.director_scores, frequencies["directors"]),
            (profile.cast_scores, frequencies["cast"]),
            (profile.runtime_bucket_scores, frequencies["runtime_buckets"]),
        ):
            for key, freq in counts.items():
                if freq > 1:
                    scores[key] *= 1 + math.log(freq) * FREQUENCY_MULTIPLIER_LOG_FACTOR

    @staticmethod
    def _apply_caps(profile: TasteProfile) -> None:
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
        content_type: str,
    ) -> TasteProfile:
        self._apply_age_decay(existing_profile)
        results = await self._process_items_bounded(new_items, content_type)

        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.debug(f"Failed to process incremental item: {result}")
                continue

            if not result:
                continue

            existing_profile.processed_items.add(new_items[i].item.id)

            features, evidence_weight = result

            self._accumulate_features(existing_profile, features, evidence_weight)

        self._apply_caps(existing_profile)

        return existing_profile

    def _apply_age_decay(self, profile: TasteProfile) -> None:
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
                score_dict[key] *= PROFILE_DECAY_FACTOR
