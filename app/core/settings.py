import base64
import zlib

from pydantic import BaseModel


class CatalogConfig(BaseModel):
    id: str  # "recommended", "loved", "watched", "genre"
    name: str | None = None
    enabled: bool = True


class UserSettings(BaseModel):
    include_watched: bool = False
    catalogs: list[CatalogConfig]


def encode_settings(settings: UserSettings) -> str:
    json_str = settings.model_dump_json(exclude_defaults=True)
    # Compress and then base64 encode to keep URL short
    compressed = zlib.compress(json_str.encode("utf-8"))
    encoded = base64.urlsafe_b64encode(compressed).decode("utf-8").rstrip("=")
    return f"settings:{encoded}"


def decode_settings(settings_str: str) -> UserSettings:
    try:
        # Remove prefix if present
        if settings_str.startswith("settings:"):
            settings_str = settings_str[9:]

        # Add padding back if necessary
        padding = 4 - (len(settings_str) % 4)
        if padding != 4:
            settings_str += "=" * padding

        compressed = base64.urlsafe_b64decode(settings_str)
        json_str = zlib.decompress(compressed).decode("utf-8")
        return UserSettings.model_validate_json(json_str)
    except Exception:
        # Fallback to default settings if decoding fails
        return get_default_settings()


def get_default_settings() -> UserSettings:
    return UserSettings(
        include_watched=False,
        catalogs=[
            CatalogConfig(id="watchly.rec", name="Recommended", enabled=True),
            CatalogConfig(id="watchly.loved", name="Because you Loved", enabled=True),
            CatalogConfig(id="watchly.watched", name="Because you Watched", enabled=True),
            CatalogConfig(id="watchly.genre", name="You might also Like", enabled=True),
        ],
    )
