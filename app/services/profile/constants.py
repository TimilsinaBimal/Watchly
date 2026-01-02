from typing import Final

# Evidence Weights (how much each interaction type contributes)
EVIDENCE_WEIGHT_LOVED: Final[float] = 3.0
EVIDENCE_WEIGHT_LIKED: Final[float] = 1.5
EVIDENCE_WEIGHT_WATCHED_HIGH: Final[float] = 1.0  # Completion ≥80%
EVIDENCE_WEIGHT_WATCHED_MEDIUM: Final[float] = 0.5  # Completion 40-79%
EVIDENCE_WEIGHT_ADDED: Final[float] = 0.3

# Feature Weights (relative importance of different feature types)
FEATURE_WEIGHT_GENRE: Final[float] = 1.0  # Most important
FEATURE_WEIGHT_KEYWORD: Final[float] = 0.8
FEATURE_WEIGHT_CREATOR: Final[float] = 0.9  # Very important when available
FEATURE_WEIGHT_ERA: Final[float] = 0.6
FEATURE_WEIGHT_COUNTRY: Final[float] = 0.4  # Less important

# Position Weights for Cast (lead actors matter more)
CAST_POSITION_LEAD: Final[float] = 1.0
CAST_POSITION_SUPPORTING: Final[float] = 0.5
CAST_POSITION_MINOR: Final[float] = 0.2

# Genre Position Weights (primary genre matters most)
GENRE_POSITION_WEIGHTS: Final[list[float]] = [1.0, 0.6, 0.3]  # First, second, third
GENRE_MAX_POSITIONS: Final[int] = 3  # Only consider top 3 genres

# Crew Job Weights (directors matter most)
CREW_JOB_DIRECTOR: Final[float] = 1.0
CREW_JOB_OTHER: Final[float] = 0.5  # All other crew roles

# Score Caps (prevent unbounded growth)
CAP_GENRE: Final[float] = 50.0
CAP_KEYWORD: Final[float] = 40.0
CAP_DIRECTOR: Final[float] = 30.0
CAP_CAST: Final[float] = 30.0
CAP_ERA: Final[float] = 25.0
CAP_COUNTRY: Final[float] = 20.0

# Recency Decay (exponential decay parameters)
RECENCY_HALF_LIFE_DAYS: Final[float] = 15.0  # 15-day half-life
RECENCY_DECAY_RATE: Final[float] = 0.98  # Daily decay multiplier (soft decay)

# Smart Sampling
SMART_SAMPLING_MAX_ITEMS: Final[int] = 30

# Frequency Multiplier (optional, subtle boost for repeated patterns)
FREQUENCY_ENABLED: Final[bool] = True
FREQUENCY_MULTIPLIER_BASE: Final[float] = 1.0
FREQUENCY_MULTIPLIER_LOG_FACTOR: Final[float] = 0.1  # Subtle boost

# Top Picks Caps (diversity constraints)
TOP_PICKS_RECENCY_CAP: Final[float] = 0.15  # Max 15% recent items (from trending/popular)
TOP_PICKS_GENRE_CAP: Final[float] = 0.50  # Max 50% per genre
TOP_PICKS_CREATOR_CAP: Final[int] = 3  # Max 3 items per creator (director/actor)
TOP_PICKS_ERA_CAP: Final[float] = 0.50  # Max 50% per era
TOP_PICKS_MIN_VOTE_COUNT: Final[int] = 250  # Lower noise filter
TOP_PICKS_MIN_RATING: Final[float] = 7.2  # Minimum weighted rating

MAXIMUM_POPULARITY_SCORE: Final[float] = 15

# Genre whitelist limit (top N genres)
GENRE_WHITELIST_LIMIT: Final[int] = 7
