from typing import Any
from urllib.parse import unquote


def parse_identifier(identifier: str) -> tuple[str | None, int | None]:
    """Parse Stremio identifier to extract IMDB ID and TMDB ID."""
    if not identifier:
        return None, None

    decoded = unquote(identifier)
    imdb_id: str | None = None
    tmdb_id: int | None = None

    for token in decoded.split(","):
        token = token.strip()
        if not token:
            continue
        if token.startswith("tt") and imdb_id is None:
            imdb_id = token
        elif token.startswith("tmdb:") and tmdb_id is None:
            try:
                tmdb_id = int(token.split(":", 1)[1])
            except (ValueError, IndexError):
                continue
        if imdb_id and tmdb_id is not None:
            break

    return imdb_id, tmdb_id


class RecommendationFiltering:
    """
    Handles exclusion sets, genre whitelists, and item filtering.
    """

    @staticmethod
    async def get_exclusion_sets(
        stremio_service: Any, library_data: dict | None = None, auth_key: str | None = None
    ) -> tuple[set[str], set[int]]:
        """
        Fetch library items and build exclusion sets for watched/loved content.
        """
        if library_data is None:
            if not auth_key:
                return set(), set()
            library_data = await stremio_service.library.get_library_items(auth_key)

        all_items = (
            library_data.get("loved", [])
            + library_data.get("watched", [])
            + library_data.get("removed", [] + library_data.get("liked"))
        )

        imdb_ids = set()
        tmdb_ids = set()

        for item in all_items:
            item_id = item.get("_id", "")
            if not item_id:
                continue

            imdb_id, tmdb_id = parse_identifier(item_id)

            if imdb_id:
                imdb_ids.add(imdb_id)
            if tmdb_id:
                tmdb_ids.add(tmdb_id)

            # Fallback parsing for common Stremio/Watchly patterns
            if item_id.startswith("tt"):
                # Handle tt123 and tt123:1:1
                base_imdb = item_id.split(":")[0]
                imdb_ids.add(base_imdb)
            elif item_id.startswith("tmdb:"):
                try:
                    tid = int(item_id.split(":")[1])
                    tmdb_ids.add(tid)
                except Exception:
                    pass

        return imdb_ids, tmdb_ids

    @staticmethod
    def filter_candidates(
        candidates: list[dict[str, Any]], watched_imdb: set[str], watched_tmdb: set[int]
    ) -> list[dict[str, Any]]:
        """
        Filter candidates against watched sets.
        Matches both TMDB (int) and IMDB (str).
        """
        filtered = []
        for item in candidates:
            tid = item.get("id")
            # 1. Check TMDB ID (integer)
            if tid and isinstance(tid, int) and tid in watched_tmdb:
                continue

            # 2. Check Stremio ID (string) if present as 'id'
            if tid and isinstance(tid, str):
                if tid in watched_imdb:
                    continue
                if tid.startswith("tmdb:"):
                    try:
                        if int(tid.split(":")[1]) in watched_tmdb:
                            continue
                    except Exception:
                        pass

            # 3. Check External IDs
            ext = item.get("external_ids", {}) or item.get("_external_ids", {})
            imdb = ext.get("imdb_id")
            if imdb and imdb in watched_imdb:
                continue

            # 4. Handle cases where TMDB ID is in 'id' but it's a string
            try:
                if tid and int(tid) in watched_tmdb:
                    continue
            except Exception:
                pass

            filtered.append(item)
        return filtered

    @staticmethod
    def get_excluded_genre_ids(user_settings: Any, content_type: str) -> list[int]:
        """Get genre IDs to exclude based on user settings."""
        if not user_settings:
            return []
        if content_type == "movie":
            return [int(g) for g in user_settings.excluded_movie_genres]
        elif content_type in ["series", "tv"]:
            return [int(g) for g in user_settings.excluded_series_genres]
        return []

    @staticmethod
    def get_genre_multiplier(genre_ids: list[int] | None, whitelist: set[int]) -> float:
        """Calculate a score multiplier based on genre preference. Blocks animation if not preferred."""
        if not whitelist:
            return 1.0

        gids = set(genre_ids or [])
        if not gids:
            return 1.0

        # If it has at least one preferred genre, full score
        if gids & whitelist:
            return 1.0

        # Otherwise, soft penalty to prioritize whitelist items without blocking variety
        return 0.4

    @staticmethod
    def passes_top_genre_whitelist(genre_ids: list[int] | None, whitelist: set[int]) -> bool:
        """Check if an item's genres match the user's top genre whitelist (Softened)."""
        if not whitelist:
            return True
        gids = set(genre_ids or [])
        if not gids:
            return True
        return True
