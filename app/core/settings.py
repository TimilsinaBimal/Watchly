from pydantic import BaseModel, Field

from app.services.poster_ratings.factory import PosterProvider


class CatalogConfig(BaseModel):
    id: str  # "watchly.rec", "watchly.theme", "watchly.item"
    name: str | None = None
    enabled: bool = True
    enabled_movie: bool = Field(default=True, description="Enable movie catalog for this configuration")
    enabled_series: bool = Field(default=True, description="Enable series catalog for this configuration")
    display_at_home: bool = Field(default=True, description="Display this catalog on home page")
    shuffle: bool = Field(default=False, description="Randomize order of items in this catalog")


class PosterRatingConfig(BaseModel):
    """Configuration for poster rating provider."""

    provider: PosterProvider = Field(description="Provider name: 'rpdb' or 'top_posters'")
    api_key: str = Field(description="API key for the provider")


class UserSettings(BaseModel):
    catalogs: list[CatalogConfig]
    language: str = "en-US"
    poster_rating: PosterRatingConfig | None = Field(default=None, description="Poster rating provider configuration")
    excluded_movie_genres: list[str] = Field(default_factory=list)
    excluded_series_genres: list[str] = Field(default_factory=list)


# Catalog descriptions for frontend
CATALOG_DESCRIPTIONS = {
    "watchly.rec": "Personalized recommendations based on your watch history, library and your reactions.",
    "watchly.loved": (
        "Recommends items similar to the content you recently loved. example: If you loved 'The Dark Knight',"
        " Then it will show similar items to 'The Dark Knight'. This takes your last 3 loved items and shuffles"
        " them and picks one at random."
    ),
    "watchly.watched": (
        "Recommends items similar to the content you recently watched. example: If you watched 'The Dark"
        " Knight', Then it will show similar items to 'The Dark Knight'. This takes your last 3 watched items"
        " and shuffles them and picks one at random."
    ),
    "watchly.creators": (
        "Recommends items from your top 5 favorite directors and top 5 favorite actors.(Favourite = Most"
        " watched items)"
    ),
    "watchly.all.loved": "Recommendations based on all your loved items",
    "watchly.liked.all": "Recommendations based on all your liked items",
    "watchly.theme": (
        "Dynamic catalogs based on your favorite genres, keyword, countries and many more.Just like netflix."
        " Example: American Horror, Based on Novel or Book etc. This will show atmost 4 catalogs each for"
        " movies and series. This number can vary based on your history."
    ),
}


def get_default_settings() -> UserSettings:
    return UserSettings(
        language="en-US",
        catalogs=[
            CatalogConfig(
                id="watchly.rec",
                name="Top Picks for You",
                enabled=True,
                enabled_movie=True,
                enabled_series=True,
                display_at_home=True,
                shuffle=False,
            ),
            CatalogConfig(
                id="watchly.loved",
                name="More Like",
                enabled=True,
                enabled_movie=True,
                enabled_series=True,
                display_at_home=True,
                shuffle=False,
            ),
            CatalogConfig(
                id="watchly.watched",
                name="Because you watched",
                enabled=True,
                enabled_movie=True,
                enabled_series=True,
                display_at_home=True,
                shuffle=False,
            ),
            CatalogConfig(
                id="watchly.theme",
                name="Genre & Keyword Catalogs",
                enabled=True,
                enabled_movie=True,
                enabled_series=True,
                display_at_home=True,
                shuffle=False,
            ),
            CatalogConfig(
                id="watchly.creators",
                name="From your favourite Creators",
                enabled=False,
                enabled_movie=True,
                enabled_series=True,
                display_at_home=True,
                shuffle=False,
            ),
            CatalogConfig(
                id="watchly.all.loved",
                name="Based on what you loved",
                enabled=False,
                enabled_movie=True,
                enabled_series=True,
                display_at_home=True,
                shuffle=False,
            ),
            CatalogConfig(
                id="watchly.liked.all",
                name="Based on what you liked",
                enabled=False,
                enabled_movie=True,
                enabled_series=True,
                display_at_home=True,
                shuffle=False,
            ),
        ],
    )


def get_default_catalogs_for_frontend() -> list[dict]:
    """Get default catalogs formatted for frontend JavaScript."""
    settings = get_default_settings()
    catalogs = []
    for catalog in settings.catalogs:
        catalogs.append(
            {
                "id": catalog.id,
                "name": catalog.name or "",
                "enabled": catalog.enabled,
                "enabledMovie": catalog.enabled_movie,
                "enabledSeries": catalog.enabled_series,
                "display_at_home": catalog.display_at_home,
                "shuffle": catalog.shuffle,
                "description": CATALOG_DESCRIPTIONS.get(catalog.id, ""),
            }
        )
    return catalogs


class Credentials(BaseModel):
    authKey: str
    email: str
    settings: UserSettings
