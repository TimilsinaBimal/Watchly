from typing import Final

# Evidence Weights (how much each interaction type contributes)
EVIDENCE_WEIGHT_LOVED: Final[float] = 3.0
EVIDENCE_WEIGHT_LIKED: Final[float] = 1.5
EVIDENCE_WEIGHT_WATCHED_HIGH: Final[float] = 1.0  # Completion ≥80%
EVIDENCE_WEIGHT_WATCHED_MEDIUM: Final[float] = 0.5  # Completion 40-79%
EVIDENCE_WEIGHT_ADDED: Final[float] = 0.3

# Share of a capped sample handed to each signal pool; watched takes the remainder.
# Weighted toward rated titles to match the evidence weights above — a watchlist
# item contributes 0.3 where a loved one contributes 3.0, so a slot spent there
# buys a tenth of the signal for the same TMDB lookups.
SAMPLING_QUOTA_RATED: Final[float] = 0.55
SAMPLING_QUOTA_ADDED: Final[float] = 0.10

# Feature Weights (relative importance of different feature types)
FEATURE_WEIGHT_GENRE: Final[float] = 0.9  # Most important
FEATURE_WEIGHT_KEYWORD: Final[float] = 0.7
FEATURE_WEIGHT_CREATOR: Final[float] = 0.9  # Very important when available
FEATURE_WEIGHT_ERA: Final[float] = 0.6
FEATURE_WEIGHT_RUNTIME: Final[float] = 0.3  # Runtime bucket preference
FEATURE_WEIGHT_COUNTRY: Final[float] = 0.3  # Less important

# Position Weights for Cast (lead actors matter more)
CAST_POSITION_LEAD: Final[float] = 1.0
CAST_POSITION_MINOR: Final[float] = 0.2

# Genre Position Weights (primary genre matters most)
GENRE_POSITION_WEIGHTS: Final[list[float]] = [1.0, 0.8, 0.5]  # First, second, third
GENRE_MAX_POSITIONS: Final[int] = 3  # Only consider top 3 genres

# Score Caps (prevent unbounded growth)
CAP_GENRE: Final[float] = 50.0
CAP_KEYWORD: Final[float] = 40.0
CAP_DIRECTOR: Final[float] = 30.0
CAP_CAST: Final[float] = 30.0
CAP_ERA: Final[float] = 25.0
CAP_RUNTIME: Final[float] = 25.0
CAP_COUNTRY: Final[float] = 20.0

# Recency Decay (exponential decay parameters)
RECENCY_HALF_LIFE_DAYS: Final[float] = 30.0

# Smart Sampling
# Was 30, which starved the parts of the profile that need volume: the creators
# catalog only keeps a director or actor appearing at least twice (MIN_FREQUENCY in
# recommendation/creators.py), and almost nobody recurs across 30 items. Top genres
# saturate long before this — CAP_GENRE is reached after roughly 20 loved items — so
# the gain here is in the long tail of keywords, creators and countries that the
# theme and creator rows read from. Still bounded rather than unlimited: past a few
# hundred items the top-N rankings stop moving, and enrichment costs ~2 TMDB calls
# per item.
SMART_SAMPLING_MAX_ITEMS: Final[int] = 200

# Frequency Multiplier (optional, subtle boost for repeated patterns)
FREQUENCY_ENABLED: Final[bool] = True
FREQUENCY_MULTIPLIER_BASE: Final[float] = 1.0
FREQUENCY_MULTIPLIER_LOG_FACTOR: Final[float] = 0.1  # Subtle boost

# Top Picks Caps (diversity constraints)
TOP_PICKS_GENRE_CAP: Final[float] = 0.50  # Max 50% per genre

# Runtime Bucket Boundaries (in minutes)
RUNTIME_BUCKET_SHORT_MAX_SERIES: Final[int] = 30  # < 30 min
RUNTIME_BUCKET_MEDIUM_MAX_SERIES: Final[int] = 60  # 30-60 min, > 60 is long
RUNTIME_BUCKET_SHORT_MAX_MOVIE: Final[int] = 120  # < 120 min
RUNTIME_BUCKET_MEDIUM_MAX_MOVIE: Final[int] = 180  # 120-180 min, > 180 is long

# Profile Decay Settings
PROFILE_DECAY_ENABLED: Final[bool] = True
PROFILE_DECAY_FACTOR: Final[float] = 0.98  # 2% decay per update
