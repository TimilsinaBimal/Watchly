RECOMMENDATIONS_CATALOG_NAME: str = "Top Picks For You"
DEFAULT_CATALOG_LIMIT: int = 20

MAX_CATALOG_ITEMS: int = 100

DEFAULT_CONCURRENCY_LIMIT: int = 30

DEFAULT_MINIMUM_RATING_FOR_THEME_BASED_MOVIE: float = 7.2
DEFAULT_MINIMUM_RATING_FOR_THEME_BASED_TV: float = 6.8


# Bumped whenever the scoring maths changes, so cached profiles built by older
# code get dropped on read instead of being served with stale numbers until TTL.
# Lives here rather than in profile/constants.py because user_cache reads it, and
# importing anything under app.services.profile pulls in ProfileService via that
# package's __init__ — a cycle.
# v2: Trakt/Simkl items are scored by ScoringService instead of a flat 50.0.
# v3: the sampler sorts by score, so a capped sample is the strongest items
#     rather than an arbitrary slice of the library.
PROFILE_SCORING_VERSION: int = 3

# cache keys
LIBRARY_ITEMS_KEY: str = "watchly:library_items:{token}"
PROFILE_KEY: str = "watchly:profile:{token}:{content_type}"
WATCHED_SETS_KEY: str = "watchly:watched_sets:{token}:{content_type}"
CATALOG_KEY: str = "watchly:catalog:{token}:{type}:{id}"

# Bounded TTL for per-user caches (library items, profile, watched sets,
# library hash, last-build timestamp). Refreshed on every read so an active
# user's data effectively never expires, but a stale install gets cleaned up
# by Redis instead of growing forever. The user's main token key is NOT
# subject to this — that follows TOKEN_TTL_SECONDS.
USER_CACHE_TTL_SECONDS: int = 60 * 60 * 24 * 90  # 90 days


DISCOVER_ONLY_EXTRA: list[dict] = [{"name": "genre", "isRequired": True, "options": ["All"], "optionsLimit": 1}]


# Single source of truth for the "Discovery" preference. Every threshold is a
# TMDB /discover filter (vote_count/vote_average), so each mode is pushed into the
# query AND re-checked post-fetch with no contradiction. "Reach" is expressed via
# vote_count — a stable, queryable proxy — instead of TMDB's volatile, unfilterable
# popularity score: high floor = mainstream/widely-seen, low ceiling = hidden gem.
DISCOVERY_SETTINGS: dict = {
    "mainstream": {
        "vote_average.gte": 6.2,
        "vote_count.gte": 1500,
    },
    "balanced": {
        "vote_average.gte": 6.7,
        "vote_count.gte": 250,
    },
    "gems": {
        "vote_average.gte": 7.2,
        "vote_count.gte": 150,
        "vote_count.lte": 4000,
    },
    "all": {
        "vote_average.gte": 5.0,
        "vote_count.gte": 50,
    },
}
