from typing import Any


def content_type_to_mtype(content_type: str) -> str:
    return "tv" if content_type in ("tv", "series") else "movie"


def year_to_era(year: int) -> str:
    if year < 1970:
        return "pre-1970s"
    elif year < 1980:
        return "1970s"
    elif year < 1990:
        return "1980s"
    elif year < 2000:
        return "1990s"
    elif year < 2010:
        return "2000s"
    elif year < 2020:
        return "2010s"
    else:
        return "2020s"


async def resolve_tmdb_id(item_id: str, tmdb_service: Any) -> int | None:
    """Resolve item ID to TMDB ID.

    Handles formats: tmdb:123, tt123456, or plain integer.
    """
    if item_id.startswith("tmdb:"):
        try:
            return int(item_id.split(":")[1])
        except (ValueError, IndexError):
            return None
    elif item_id.startswith("tt"):
        tmdb_id, _ = await tmdb_service.find_by_imdb_id(item_id)
        return tmdb_id
    else:
        try:
            return int(item_id)
        except ValueError:
            return None
