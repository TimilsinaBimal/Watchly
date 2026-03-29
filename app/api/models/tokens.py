from typing import Literal

from pydantic import BaseModel, Field

from app.core.settings import DEFAULT_YEAR_MIN, CatalogConfig, PosterRatingConfig, get_default_year_max


class TokenRequest(BaseModel):
    authKey: str | None = Field(default=None, description="Stremio auth key")
    email: str | None = Field(default=None, description="Stremio account email")
    password: str | None = Field(default=None, description="Stremio account password")
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
    gemini_api_key: str | None = Field(default=None, description="Gemini API Key for AI features")
    tmdb_api_key: str | None = Field(default=None, description="TMDB API Key")


class TokenResponse(BaseModel):
    token: str
    manifestUrl: str
    expiresInSeconds: int | None = Field(
        default=None,
        description="Number of seconds before the token expires (None means it does not expire)",
    )
