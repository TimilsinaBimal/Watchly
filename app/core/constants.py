RECOMMENDATIONS_CATALOG_NAME: str = "Top Picks For You"
DEFAULT_CATALOG_LIMIT: int = 20

MAX_CATALOG_ITEMS: int = 100

DEFAULT_CONCURRENCY_LIMIT: int = 30

DEFAULT_MINIMUM_RATING_FOR_THEME_BASED_MOVIE: float = 7.2
DEFAULT_MINIMUM_RATING_FOR_THEME_BASED_TV: float = 6.8


# cache keys
LIBRARY_ITEMS_KEY: str = "watchly:library_items:{token}"
PROFILE_KEY: str = "watchly:profile:{token}:{content_type}"
WATCHED_SETS_KEY: str = "watchly:watched_sets:{token}:{content_type}"
CATALOG_KEY: str = "watchly:catalog:{token}:{type}:{id}"


DISCOVER_ONLY_EXTRA: list[dict] = [{"name": "genre", "isRequired": True, "options": ["All"], "optionsLimit": 1}]


DISCOVERY_SETTINGS: dict = {
    "mainstream": {
        "popularity.gte": 30,
        "vote_average.gte": 6.2,
        "vote_count.gte": 500,
    },
    "balanced": {
        "popularity.lte": 30,
        "vote_average.gte": 6.7,
        "vote_count.gte": 250,
    },
    "gems": {
        "popularity.lte": 15,
        "vote_average.gte": 7.2,
        "vote_count.gte": 100,
    },
    "all": {
        "popularity.gte": 0,
        "vote_average.gte": 5.0,
        "vote_count.gte": 100,
    },
}
