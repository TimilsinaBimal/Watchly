from typing import Final

# Evidence Weights (how much each interaction type contributes)
EVIDENCE_WEIGHT_LOVED: Final[float] = 3.0
EVIDENCE_WEIGHT_LIKED: Final[float] = 1.5
EVIDENCE_WEIGHT_WATCHED_HIGH: Final[float] = 1.0  # Completion ≥80%
EVIDENCE_WEIGHT_WATCHED_MEDIUM: Final[float] = 0.5  # Completion 40-79%
EVIDENCE_WEIGHT_ADDED: Final[float] = 0.3

# Feature Weights (relative importance of different feature types)
FEATURE_WEIGHT_GENRE: Final[float] = 0.9  # Most important
FEATURE_WEIGHT_KEYWORD: Final[float] = 0.7
FEATURE_WEIGHT_CREATOR: Final[float] = 0.9  # Very important when available
FEATURE_WEIGHT_ERA: Final[float] = 0.6
FEATURE_WEIGHT_RUNTIME: Final[float] = 0.3  # Runtime bucket preference
FEATURE_WEIGHT_COUNTRY: Final[float] = 0.3  # Less important

# Position Weights for Cast (lead actors matter more)
CAST_POSITION_LEAD: Final[float] = 1.0
CAST_POSITION_SUPPORTING: Final[float] = 0.5
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
TOP_PICKS_MIN_VOTE_COUNT: Final[int] = 100  # Default base (dynamic based on settings)
TOP_PICKS_MIN_RATING: Final[float] = 6.0  # Default base (dynamic based on settings)

MAXIMUM_POPULARITY_SCORE: Final[float] = 100.0  # Increased from 15.0 to allow popular items

# Runtime Bucket Boundaries (in minutes)
RUNTIME_BUCKET_SHORT_MAX_SERIES: Final[int] = 30  # < 30 min
RUNTIME_BUCKET_MEDIUM_MAX_SERIES: Final[int] = 60  # 30-60 min, > 60 is long
RUNTIME_BUCKET_SHORT_MAX_MOVIE: Final[int] = 120  # < 120 min
RUNTIME_BUCKET_MEDIUM_MAX_MOVIE: Final[int] = 180  # 120-180 min, > 180 is long

# Profile Decay Settings
PROFILE_DECAY_ENABLED: Final[bool] = True
PROFILE_DECAY_FACTOR: Final[float] = 0.98  # 2% decay per update
PROFILE_DECAY_DAYS_THRESHOLD: Final[int] = 30  # Apply decay after 7 days

# TMDB Genre ID to Name mapping
GENRE_MAP = {
    # Movie Genres
    28: "Action",
    12: "Adventure",
    16: "Animation",
    35: "Comedy",
    80: "Crime",
    99: "Documentary",
    18: "Drama",
    10751: "Family",
    14: "Fantasy",
    36: "History",
    27: "Horror",
    10402: "Music",
    9648: "Mystery",
    10749: "Romance",
    878: "Science Fiction",
    10770: "TV Movie",
    53: "Thriller",
    10752: "War",
    37: "Western",
    # TV Genres
    10759: "Action & Adventure",
    10762: "Kids",
    10763: "News",
    10764: "Reality",
    10765: "Sci-Fi & Fantasy",
    10766: "Soap",
    10767: "Talk",
    10768: "War & Politics",
}
