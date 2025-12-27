from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.version import __version__


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="allow",
    )

    TMDB_API_KEY: str | None = None
    PORT: int = 8000
    ADDON_ID: str = "com.bimal.watchly"
    ADDON_NAME: str = "Watchly"
    REDIS_URL: str = "redis://redis:6379/0"
    # Maximum number of connections Redis client will open per process
    # Set conservatively to avoid unbounded connection growth under high concurrency
    REDIS_MAX_CONNECTIONS: int = 20
    # If total connected clients reported by Redis exceeds this, background
    # Redis-heavy jobs will back off. Tune according to your Redis capacity.
    REDIS_CONNECTIONS_THRESHOLD: int = 100
    REDIS_TOKEN_KEY: str = "watchly:token:"
    TOKEN_SALT: str = "change-me"
    TOKEN_TTL_SECONDS: int = 0  # 0 = never expire
    ANNOUNCEMENT_HTML: str = ""
    AUTO_UPDATE_CATALOGS: bool = True
    CATALOG_REFRESH_INTERVAL_SECONDS: int = 43200  # 12 hours
    APP_ENV: Literal["development", "production", "vercel"] = "production"
    HOST_NAME: str = "https://1ccea4301587-watchly.baby-beamup.club"

    RECOMMENDATION_SOURCE_ITEMS_LIMIT: int = 10
    LIBRARY_ITEMS_LIMIT: int = 20

    # AI
    DEFAULT_GEMINI_MODEL: str = "gemma-3-27b-it"
    GEMINI_API_KEY: str | None = None


settings = Settings()

APP_VERSION = __version__
