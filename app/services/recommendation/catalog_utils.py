import random
from typing import Any

from app.core.settings import UserSettings


def should_shuffle(user_settings: UserSettings, catalog_id: str) -> bool:
    config = next((c for c in user_settings.catalogs if c.id == catalog_id), None)
    return getattr(config, "shuffle", False) if config else False


def shuffle_data_if_needed(
    user_settings: UserSettings, catalog_id: str, data: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    if should_shuffle(user_settings, catalog_id):
        random.shuffle(data)
    return data


def clean_meta(meta: dict) -> dict | None:
    """Return a sanitized Stremio meta object without internal fields.

    Keeps only public keys and drops internal scoring/IDs/keywords/cast, etc.
    """
    allowed = {
        "id",
        "type",
        "name",
        "poster",
        "background",
        "description",
        "releaseInfo",
        "imdbRating",
        "genres",
        "runtime",
    }
    cleaned = {k: v for k, v in meta.items() if k in allowed}
    # Drop empty values
    cleaned = {k: v for k, v in cleaned.items() if v not in (None, "", [], {}, ())}

    # Normalize IMDb rating to a string with 1 decimal place
    rating = cleaned.get("imdbRating")
    if rating not in (None, ""):
        try:
            cleaned["imdbRating"] = f"{float(rating):.1f}"
        except (TypeError, ValueError):
            # Keep original value if it cannot be parsed
            pass

    imdb_id = cleaned.get("id", "")
    # if id does not start with tt, return None
    if not imdb_id.startswith("tt"):
        return None
    # Add Metahub logo URL (used by Stremio)
    cleaned["logo"] = f"https://live.metahub.space/logo/medium/{imdb_id}/img"
    return cleaned
