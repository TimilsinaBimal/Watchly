from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    TMDB_API_KEY: str | None = None
    PORT: int = 8000
    ADDON_ID: str = "com.bimal.watchly"
    ADDON_NAME: str = "Watchly"
    REDIS_URL: str = "redis://localhost:6379/0"
    TOKEN_SALT: str = "change-me"
    TOKEN_TTL_SECONDS: int = 0  # 0 = never expire
    ANNOUNCEMENT_HTML: str = ""


settings = Settings()
