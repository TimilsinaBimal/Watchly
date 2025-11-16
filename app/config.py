from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False
    )

    TMDB_API_KEY: str
    STREMIO_USERNAME: str = ""
    STREMIO_PASSWORD: str = ""
    PORT: int = 8000


settings = Settings()
