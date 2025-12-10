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
    REDIS_TOKEN_KEY: str = "watchly:token:"
    TOKEN_SALT: str = "change-me"
    TOKEN_TTL_SECONDS: int = 0  # 0 = never expire
    ANNOUNCEMENT_HTML: str = ""
    AUTO_UPDATE_CATALOGS: bool = True
    CATALOG_UPDATE_MODE: Literal["cron", "interval"] = "cron"  # "cron" for fixed times, "interval" for periodic
    CATALOG_UPDATE_CRON_SCHEDULES: list[dict] = (
        {"hour": 12, "minute": 0, "id": "catalog_refresh_noon"},
        {"hour": 0, "minute": 0, "id": "catalog_refresh_midnight"},
    )
    CATALOG_REFRESH_INTERVAL_SECONDS: int = 6 * 60 * 60  # 6 hours (used when CATALOG_UPDATE_MODE="interval")
    APP_ENV: Literal["development", "production", "vercel"] = "development"
    HOST_NAME: str = "https://1ccea4301587-watchly.baby-beamup.club"

    RECOMMENDATION_SOURCE_ITEMS_LIMIT: int = 10

    # AI
    DEFAULT_GEMINI_MODEL: str = "gemma-3-27b-it"
    GEMINI_API_KEY: str | None = None


settings = Settings()

# Get version from version.py (single source of truth)
APP_VERSION = __version__
