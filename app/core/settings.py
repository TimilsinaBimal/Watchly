from pydantic import BaseModel


class CatalogConfig(BaseModel):
    id: str  # "watchly.rec", "watchly.theme", "watchly.item"
    name: str | None = None
    enabled: bool = True


class UserSettings(BaseModel):
    catalogs: list[CatalogConfig]
    language: str = "en-US"
    rpdb_key: str | None = None
    excluded_movie_genres: list[str] = []
    excluded_series_genres: list[str] = []


def get_default_settings() -> UserSettings:
    return UserSettings(
        language="en-US",
        catalogs=[
            CatalogConfig(id="watchly.rec", name="Recommended", enabled=True),
            CatalogConfig(id="watchly.loved", name="More like what you loved", enabled=True),
            CatalogConfig(id="watchly.watched", name="Because you watched", enabled=True),
            CatalogConfig(id="watchly.theme", name="Because of Genre/Theme", enabled=True),
        ],
    )


class Credentials(BaseModel):
    authKey: str
    email: str
    settings: UserSettings
