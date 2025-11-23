from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


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
    APP_VERSION: str = "0.1.3"
    REDIS_URL: str = "redis://redis:6379/0"
    TOKEN_SALT: str = "change-me"
    TOKEN_TTL_SECONDS: int = 0  # 0 = never expire
    ANNOUNCEMENT_HTML: str = ""
    AUTO_UPDATE_CATALOGS: bool = True
    CATALOG_REFRESH_INTERVAL_SECONDS: int = 6 * 60 * 60  # 6 hours
    APP_ENV: Literal["development", "production"] = "development"
    HOST_NAME: str = "https://1ccea4301587-watchly.baby-beamup.club"

    RECOMMENDATION_SOURCE_ITEMS_LIMIT: int = 10


settings = Settings()
