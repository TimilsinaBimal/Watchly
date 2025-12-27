from pydantic import BaseModel, Field


class CatalogConfig(BaseModel):
    id: str  # "watchly.rec", "watchly.theme", "watchly.item"
    name: str | None = None
    enabled: bool = True
    enabled_movie: bool = Field(default=True, description="Enable movie catalog for this configuration")
    enabled_series: bool = Field(default=True, description="Enable series catalog for this configuration")


class UserSettings(BaseModel):
    catalogs: list[CatalogConfig]
    language: str = "en-US"
    rpdb_key: str | None = None
    excluded_movie_genres: list[str] = Field(default_factory=list)
    excluded_series_genres: list[str] = Field(default_factory=list)


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
            ),
            CatalogConfig(
                id="watchly.loved",
                name="More Like",
                enabled=True,
                enabled_movie=True,
                enabled_series=True,
            ),
            CatalogConfig(
                id="watchly.watched",
                name="Because you watched",
                enabled=True,
                enabled_movie=True,
                enabled_series=True,
            ),
            CatalogConfig(
                id="watchly.theme",
                name="Genre & Keyword Catalogs",
                enabled=True,
                enabled_movie=True,
                enabled_series=True,
            ),
            CatalogConfig(
                id="watchly.creators",
                name="From your favourite Creators",
                enabled=False,
                enabled_movie=True,
                enabled_series=True,
            ),
            CatalogConfig(
                id="watchly.all.loved",
                name="Based on what you loved",
                enabled=False,
                enabled_movie=True,
                enabled_series=True,
            ),
            CatalogConfig(
                id="watchly.liked.all",
                name="Based on what you liked",
                enabled=False,
                enabled_movie=True,
                enabled_series=True,
            ),
        ],
    )


class Credentials(BaseModel):
    authKey: str
    email: str
    settings: UserSettings
