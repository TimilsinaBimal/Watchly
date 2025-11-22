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
    TMDB_API_URL: str = "https://api.themoviedb.org/3"
    TMDB_ADDON_CONFIG_DICT = {
        "provideImdbId": "true",
        "returnImdbId": "true",
        "language": "en-US",
        "enableEpisodeProvider": "true",
        "useDomain": "",
        "cacheItemExpiryInHours": "24",
        "returnPoster": "true",
        "returnBackdrop": "true",
        "returnStreamingData": "true",
        "streamingDataLanguage": "en",
        "disableImdbLookup": "false",
        "type": "catalog",
        "enableHopAgeRating": "false",
        "enableAgeRating": "false",
        "showAgeRatingWithImdbRating": "false",
    }
    TMDB_ADDON_CONFIG: str = (
        "N4IgDgTg9gbglgEwKYEkC2CBGKEgFwgAuEArkiADQgRKEkQB26WO+Rp5VANgIYMDmJHv3IEkDALQBVAMqUQAZ2JIeaOAPwBtALpUAxj0I8uUfgq27FKiHoAWAUQY9MXJLgIAzYws4gDSgGEoEgZCfABWKgVbKAB3AEERACVDdX4UBgBxcRpzAmIyeXFnV0SkFMI0ti8uH3louLKKtIB1OEJbZkxmjU9vcgBfIA"  # noqa
    )
    TMDB_ADDON_HOST: str = "https://94c8cb9f702d-tmdb-addon.baby-beamup.club"
    PORT: int = 8000
    ADDON_ID: str = "com.bimal.watchly"
    ADDON_NAME: str = "Watchly"
    REDIS_URL: str = "redis://localhost:6379/0"
    TOKEN_SALT: str = "change-me"
    TOKEN_TTL_SECONDS: int = 0  # 0 = never expire
    ANNOUNCEMENT_HTML: str = ""
    AUTO_UPDATE_CATALOGS: bool = True
    CATALOG_REFRESH_INTERVAL_SECONDS: int = 21600  # 6 hours
    APP_ENV: Literal["development", "production"] = "development"

    @property
    def TMDB_ADDON_URL(self) -> str:
        return f"{self.TMDB_ADDON_HOST}/{self.TMDB_ADDON_CONFIG}"


settings = Settings()
