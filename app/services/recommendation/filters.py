from app.shared.ids import parse_identifier


class FilterEngine:
    """Handles exclusion logic and filtering criteria."""

    def __init__(self, stremio_service=None, library_data=None):
        self.stremio_service = stremio_service
        self._library_data = library_data
        self._cache_exclusion = None

    async def get_exclusion_sets(self) -> tuple[set[str], set[int]]:
        """
        Fetch library items and build strict exclusion sets for watched content.
        Excludes watched items.
        Memoized for the lifetime of this instance (request-scoped).
        """
        if self._cache_exclusion:
            return self._cache_exclusion

        if self._library_data is None and self.stremio_service:
            self._library_data = await self.stremio_service.get_library_items()

        library_data = self._library_data or {}
        watched_items = library_data.get("watched", [])

        imdb_ids = set()
        tmdb_ids = set()

        for item in watched_items:
            iid = item.get("_id", "")

            if iid.startswith("tt"):
                imdb_ids.add(iid)
            elif iid.startswith("tmdb:"):
                try:
                    tmdb_ids.add(int(iid.split(":")[1]))
                except Exception:
                    pass

            # Try parsing if complex format
            imdb, tmdb = parse_identifier(iid)
            if imdb:
                imdb_ids.add(imdb)
            if tmdb:
                tmdb_ids.add(tmdb)

        self._cache_exclusion = (imdb_ids, tmdb_ids)
        return imdb_ids, tmdb_ids

    def passes_genre_filter(self, item_genres: list[int], excluded_ids: set[int]) -> bool:
        if not item_genres or not excluded_ids:
            return True
        return not bool(set(item_genres) & excluded_ids)
