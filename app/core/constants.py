RECOMMENDATIONS_CATALOG_NAME: str = "Top Picks For You"
DEFAULT_MIN_ITEMS: int = 8
DEFAULT_CATALOG_LIMIT: int = 20

DEFAULT_CONCURRENCY_LIMIT: int = 30

DEFAULT_MINIMUM_RATING_FOR_THEME_BASED_MOVIE: float = 7.2
DEFAULT_MINIMUM_RATING_FOR_THEME_BASED_TV: float = 6.8


# cache keys
LIBRARY_ITEMS_KEY: str = "watchly:library_items:{token}"
PROFILE_KEY: str = "watchly:profile:{token}:{content_type}"
WATCHED_SETS_KEY: str = "watchly:watched_sets:{token}:{content_type}"
CATALOG_KEY: str = "watchly:catalog:{token}:{type}:{id}"


DISCOVER_ONLY_EXTRA: list[dict] = [{"name": "genre", "isRequired": True, "options": ["All"], "optionsLimit": 1}]
