from pydantic import BaseModel, Field


class CatalogConfig(BaseModel):
    id: str  # "watchly.rec", "watchly.theme", "watchly.item"
    name: str | None = None
    enabled: bool = True
    enabled_movie: bool = Field(default=True, description="Enable movie catalog for this configuration")
    enabled_series: bool = Field(default=True, description="Enable series catalog for this configuration")
    display_at_home: bool = Field(default=True, description="Display this catalog on home page")
    shuffle: bool = Field(default=False, description="Randomize order of items in this catalog")


class UserSettings(BaseModel):
    catalogs: list[CatalogConfig]
    language: str = "en-US"
    rpdb_key: str | None = None
    excluded_movie_genres: list[str] = Field(default_factory=list)
    excluded_series_genres: list[str] = Field(default_factory=list)


# Catalog descriptions for frontend
CATALOG_DESCRIPTIONS = {
    "watchly.rec": "Personalized recommendations based on your library",
    "watchly.loved": "Recommendations similar to content you explicitly loved",
    "watchly.watched": "Recommendations based on your recent watch history",
    "watchly.creators": "Movies and series from your top 5 favorite directors and top 5 favorite actors",
    "watchly.all.loved": "Recommendations based on all your loved items",
    "watchly.liked.all": "Recommendations based on all your liked items",
    "watchly.theme": (
        "Dynamic catalogs based on your favorite genres, keyword, countries and many more."
        "Just like netflix. Example: American Horror, Based on Novel or Book etc."
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
