from typing import Literal

from pydantic import BaseModel, Field

from app.core.settings import DEFAULT_YEAR_MIN, CatalogConfig, LLMConfig, PosterRatingConfig, get_default_year_max


class TokenRequest(BaseModel):
    authKey: str | None = Field(default=None, description="Stremio auth key")
    email: str | None = Field(default=None, description="Stremio account email")
    password: str | None = Field(default=None, description="Stremio account password")
    stremio_profile_id: str | None = Field(default=None, description="Verified Stremio profile ID")
    stremio_profile_name: str | None = Field(default=None, description="Verified Stremio profile name")
    catalogs: list[CatalogConfig] | None = Field(default=None, description="Catalog configuration")
    language: str = Field(default="en-US", description="Language for TMDB API")
    poster_rating: PosterRatingConfig | None = Field(default=None, description="Poster rating provider configuration")
    excluded_movie_genres: list[str] = Field(default_factory=list, description="List of movie genre IDs to exclude")
    excluded_series_genres: list[str] = Field(default_factory=list, description="List of series genre IDs to exclude")
    popularity: Literal["mainstream", "balanced", "gems", "all"] = Field(
        default="balanced", description="Popularity for TMDB API"
    )
    year_min: int = Field(default=DEFAULT_YEAR_MIN, description="Minimum release year for TMDB API")
    year_max: int = Field(default_factory=get_default_year_max, description="Maximum release year for TMDB API")
    sorting_order: Literal["default", "movies_first", "series_first"] = Field(
        default="default", description="Order of movies and series catalogs"
    )
    simkl_api_key: str | None = Field(default=None, description="Simkl API Key for the user")
    llm: LLMConfig | None = Field(default=None, description="LLM provider configuration for AI features")
    gemini_api_key: str | None = Field(default=None, description="Legacy Gemini API key (superseded by llm)")
    tmdb_api_key: str | None = Field(default=None, description="TMDB API Key")
    trakt_access_token: str | None = Field(default=None, description="Trakt OAuth access token")
    trakt_refresh_token: str | None = Field(default=None, description="Trakt OAuth refresh token")
    trakt_token_expires_at: int | None = Field(
        default=None, description="Epoch seconds when the Trakt access token expires"
    )
    simkl_access_token: str | None = Field(default=None, description="Simkl OAuth access token")
    watch_history_source: Literal["stremio", "trakt", "simkl"] = Field(
        default="stremio", description="Source for watch history"
    )


class TraktTokens(BaseModel):
    access_token: str
    refresh_token: str
    expires_at: int


class TokenResponse(BaseModel):
    token: str
    manifestUrl: str
    expiresInSeconds: int | None = Field(
        default=None,
        description="Number of seconds before the token expires (None means it does not expire)",
    )
    refreshedTrakt: TraktTokens | None = Field(
        default=None,
        description=(
            "Set when the submitted Trakt tokens were expired and refreshed. Trakt rotates refresh tokens, "
            "so the client must replace its copy or the next submit will present a spent refresh token."
        ),
    )
