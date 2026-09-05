from datetime import datetime
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator, model_validator

from app.services.poster_ratings.factory import PosterProvider

# The seed pool is the 3 most-recent loved + 3 most-recent watched items. Capped
# below the pool so a home screen is never mostly "Because you watched" rows.
MAX_ITEM_ROWS = 3


class CatalogConfig(BaseModel):
    id: str  # "watchly.rec", "watchly.theme", "watchly.item"
    name: str | None = None
    enabled: bool = True
    enabled_movie: bool = Field(default=True, description="Enable movie catalog for this configuration")
    enabled_series: bool = Field(default=True, description="Enable series catalog for this configuration")
    display_at_home: bool = Field(default=True, description="Display this catalog on home page")
    shuffle: bool = Field(default=False, description="Randomize order of items in this catalog")
    rows: int = Field(
        default=1, ge=1, le=MAX_ITEM_ROWS, description="Rows per content type; only watchly.item emits more than one"
    )

    @field_validator("name", mode="before")
    @classmethod
    def _blank_name_is_none(cls, v):
        # Users can clear the rename field in the configure UI; persisting "" or
        # whitespace would produce a blank catalog row in Stremio. Normalize to
        # None so downstream code falls back to the default catalog name.
        if isinstance(v, str):
            stripped = v.strip()
            return stripped or None
        return v


class PosterRatingConfig(BaseModel):
    """Configuration for poster rating provider."""

    provider: Literal[PosterProvider.RPDB.value, PosterProvider.TOP_POSTERS.value, PosterProvider.CUSTOM.value] = Field(
        description="Provider name: 'rpdb', 'top_posters', or 'custom'"
    )
    api_key: str | None = Field(default=None, description="API key for the provider (optional for 'custom')")
    url_template: str | None = Field(
        default=None,
        description="URL template with {imdb_id}/{type}/{api_key}/{language}/{language_short} for 'custom'",
    )

    @model_validator(mode="after")
    def _check_provider_requirements(self) -> "PosterRatingConfig":
        if self.provider == PosterProvider.CUSTOM.value:
            template = (self.url_template or "").strip()
            parsed = urlparse(template)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                raise ValueError("custom poster provider needs an http(s) url_template")
            if "{imdb_id}" not in template:
                raise ValueError("custom poster url_template must contain {imdb_id}")
        elif not (self.api_key or "").strip():
            raise ValueError(f"{self.provider} poster provider requires an api_key")
        return self


LLM_PROVIDER_DEFAULT_MODELS = {
    "gemini": "gemini-2.5-flash",
    "openai": "gpt-5-mini",
    "anthropic": "claude-haiku-4-5",
    "openrouter": "openai/gpt-4o-mini",
}


class LLMConfig(BaseModel):
    """User-supplied LLM provider configuration for AI features."""

    provider: Literal["gemini", "openai", "anthropic", "openrouter"]
    api_key: str = Field(description="API key for the provider")
    model: str | None = Field(default=None, description="Model id; falls back to the provider default")

    def resolved_model(self) -> str:
        return self.model or LLM_PROVIDER_DEFAULT_MODELS[self.provider]


def get_current_year() -> int:
    return datetime.now().year


DEFAULT_YEAR_MIN = 1970


def get_default_year_max() -> int:
    return get_current_year()


def get_default_year_range() -> dict[str, int]:
    return {
        "min": DEFAULT_YEAR_MIN,
        "max": get_default_year_max(),
    }


class UserSettings(BaseModel):
    catalogs: list[CatalogConfig]
    language: str = "en-US"
    poster_rating: PosterRatingConfig | None = Field(default=None, description="Poster rating provider configuration")
    excluded_movie_genres: list[str] = Field(default_factory=list)
    excluded_series_genres: list[str] = Field(default_factory=list)
    year_min: int = Field(default=DEFAULT_YEAR_MIN, description="Minimum release year")
    year_max: int = Field(default_factory=get_default_year_max, description="Maximum release year")
    popularity: Literal["mainstream", "balanced", "gems", "all"] = Field(
        default="balanced", description="Popularity preference"
    )
    sorting_order: Literal["default", "movies_first", "series_first"] = Field(
        default="default", description="Order of movies and series catalogs"
    )
    simkl_api_key: str | None = Field(default=None, description="Simkl API Key for the user")
    llm: LLMConfig | None = Field(default=None, description="LLM provider configuration for AI features")
    # Superseded by `llm`; kept so accounts configured before multi-provider
    # support keep their AI features (see resolve_llm_config).
    gemini_api_key: str | None = Field(default=None, description="Gemini API Key for AI-powered features")
    tmdb_api_key: str | None = Field(default=None, description="TMDB API Key (used if set; else server config)")
    trakt_access_token: str | None = Field(default=None, description="Trakt OAuth access token")
    trakt_refresh_token: str | None = Field(default=None, description="Trakt OAuth refresh token")
    trakt_token_expires_at: int | None = Field(
        default=None, description="Epoch seconds when the Trakt access token expires"
    )
    simkl_access_token: str | None = Field(default=None, description="Simkl OAuth access token")
    watch_history_source: Literal["stremio", "trakt", "simkl"] = Field(
        default="stremio", description="Source for watch history used in profile building"
    )


# Catalog descriptions for frontend
CATALOG_DESCRIPTIONS = {
    "watchly.rec": "Personalized recommendations based on your watch history, library and your reactions.",
    "watchly.item": (
        "Recommends items similar to one you recently watched or loved. Each row's seed is picked at random"
        " from a pool of your 3 most-recent loved items + your 3 most-recent watched items, with no seed"
        " repeated across rows. The catalog title becomes 'Because you loved <title>' or 'Because you watched"
        " <title>' depending on which bucket the seed came from."
    ),
    "watchly.creators": (
        "Recommends items from your recurring directors and lead actors — those who appear across multiple"
        " items in your library, not just one. Single-appearance creators are filtered out so the catalog"
        " actually reflects who you keep coming back to."
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
                id="watchly.item",
                name="Because you Watched/Loved",
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
                "rows": catalog.rows,
                "description": CATALOG_DESCRIPTIONS.get(catalog.id, ""),
            }
        )
    return catalogs


def resolve_llm_config(user_settings: UserSettings | None) -> LLMConfig | None:
    """The user's LLM config, or their legacy gemini_api_key wrapped as one.

    Returns None when the user supplied no key — AI features are disabled then;
    there is deliberately no server-key fallback.
    """
    if user_settings is None:
        return None
    if user_settings.llm and user_settings.llm.api_key:
        return user_settings.llm
    if user_settings.gemini_api_key:
        return LLMConfig(provider="gemini", api_key=user_settings.gemini_api_key)
    return None


def resolve_tmdb_api_key(user_settings: UserSettings | None) -> str | None:
    """Use TMDB API key from user settings (Redis) if set, else from server config."""
    from app.core.config import settings

    if user_settings and user_settings.tmdb_api_key:
        return user_settings.tmdb_api_key
    return settings.TMDB_API_KEY


class Credentials(BaseModel):
    authKey: str
    email: str
    settings: UserSettings
