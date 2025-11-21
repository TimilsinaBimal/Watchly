from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    TMDB_API_KEY: str | None = None
    TMDB_ADDON_URL: str = "https://94c8cb9f702d-tmdb-addon.baby-beamup.club/N4IgTgDgJgRg1gUwJ4gFwgC4AYC0AzMBBHSWEAGhAjAHsA3ASygQEkBbWFqNTMAVwQVwCDHzAA7dp27oM-QZQA2AQ3EBzPsrWD0CcTgCqAZSEBnOQmVsG6tAG0AupQDGyjMsU01p+05CnLMGcACwBRcWUYRQQZEDwPAKFXcwBhGj5xDDQAVkpTYJoAdwBBbQAlNxs1FnEAcT1CH1l5IT1I6NKECowqnjkBMwKS8sr1AHUGDGCpGG7e9HjFRIBfIA"
    PORT: int = 8000
    ADDON_ID: str = "com.bimal.watchly"
    ADDON_NAME: str = "Watchly"
    REDIS_URL: str = "redis://localhost:6379/0"
    TOKEN_SALT: str = "change-me"
    TOKEN_TTL_SECONDS: int = 0  # 0 = never expire
    ANNOUNCEMENT_HTML: str = ""
    AUTO_UPDATE_CATALOGS: bool = True
    CATALOG_REFRESH_INTERVAL_SECONDS: int = 21600  # 6 hours


settings = Settings()
