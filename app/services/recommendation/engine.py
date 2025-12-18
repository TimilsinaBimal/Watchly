import asyncio

from app.core.settings import UserSettings
from app.services.discovery import DiscoveryEngine
from app.services.scoring import ScoringService
from app.services.stremio import StremioService
from app.services.tmdb import get_tmdb_service
from app.services.user_profile import UserProfileService

from .fetcher import MetadataFetcher
from .filters import FilterEngine


class RecommendationEngine:
    """
    Orchestrates the recommendation process using smaller, focused components.
    """

    def __init__(
        self,
        stremio_service: StremioService,
        language: str = "en-US",
        user_settings: UserSettings = None,
        token=None,
        library_data=None,
    ):
        self.stremio = stremio_service
        self.tmdb = get_tmdb_service(language)
        self.settings = user_settings
        self.filter_engine = FilterEngine(stremio_service, library_data)
        self.fetcher = MetadataFetcher(self.tmdb, user_settings)
        self.discovery = DiscoveryEngine(language)
        self.user_profile = UserProfileService(language)
        self.scoring = ScoringService()
        self.per_item_limit = 20
        self._library_data = library_data  # Hold onto raw data if needed

    async def get_recommendations_for_item(self, item_id: str) -> list[dict]:
        """
        Get similar/recommended items for a source item ID.
        """
        # 1. Resolve ID to TMDB
        tmdb_id = None
        media_type = "movie"

        if item_id.startswith("tt"):
            tmdb_id, media_type = await self.tmdb.find_by_imdb_id(item_id)
        elif item_id.startswith("tmdb:"):
            try:
                tmdb_id = int(item_id.split(":")[1])
                media_type = "movie"
            except Exception:
                pass
        else:
            pass

        if not tmdb_id:
            return []

        # 2. Fetch Candidates
        candidates = []
        tasks = [self.tmdb.get_recommendations(tmdb_id, media_type), self.tmdb.get_similar(tmdb_id, media_type)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        seen_ids = set()
        for batch in results:
            if isinstance(batch, dict):
                for item in batch.get("results", []):
                    if item["id"] not in seen_ids:
                        candidates.append(item)
                        seen_ids.add(item["id"])

        # 3. Filter Candidates
        watched_imdb, watched_tmdb = await self.filter_engine.get_exclusion_sets()

        if item_id.startswith("tt"):
            watched_imdb.add(item_id)
        if tmdb_id:
            watched_tmdb.add(tmdb_id)

        valid_candidates = []
        for c in candidates:
            if c["id"] in watched_tmdb:
                continue
            valid_candidates.append(c)
            if len(valid_candidates) >= 40:
                break

        # 4. Fetch Metadata & Format
        final_items = await self._fetch_and_format(valid_candidates, media_type, watched_imdb)
        return final_items[: self.per_item_limit]

    async def get_recommendations_for_theme(self, theme_id: str, content_type: str, limit: int = 20) -> list[dict]:
        """
        Fetch recommendations based on theme parameters encoded in ID.
        Format: watchly.theme.g<id>[-<id>].k<id>[-<id>].ct<code>.y<year>...
        """
        params = {}
        parts = theme_id.replace("watchly.theme.", "").split(".")

        for part in parts:
            if part.startswith("g"):
                params["with_genres"] = part[1:].replace("-", "|")
            elif part.startswith("k"):
                params["with_keywords"] = part[1:].replace("-", "|")
            elif part.startswith("ct"):
                params["with_origin_country"] = part[2:]
            elif part.startswith("y"):
                try:
                    year = int(part[1:])
                    params["primary_release_date.gte"] = f"{year}-01-01"
                    params["primary_release_date.lte"] = f"{year+9}-12-31"
                except Exception:
                    pass
            elif part == "sort-vote":
                params["sort_by"] = "vote_average.desc"
                params["vote_count.gte"] = 200

        if "sort_by" not in params:
            params["sort_by"] = "popularity.desc"

        # Use TMDB Discover
        data = await self.tmdb.get_discover(content_type, **params)
        candidates = data.get("results", [])

        # Filter
        watched_imdb, watched_tmdb = await self.filter_engine.get_exclusion_sets()

        valid_candidates = [c for c in candidates if c["id"] not in watched_tmdb]

        # Fetch Metadata
        return await self._fetch_and_format(valid_candidates, content_type, watched_imdb, limit=limit)

    async def get_recommendations(
        self, content_type: str, source_items_limit: int = 10, max_results: int = 20
    ) -> list[dict]:
        """
        Personalized recommendations using UserProfile and Discovery Engine.
        """
        # 1. Build Profile
        # We need scored items. Reuse library data from FilterEngine if possible.
        if self._library_data is None:
            self._library_data = await self.stremio.get_library_items()

        # Combine watched and loved
        items = self._library_data.get("watched", []) + self._library_data.get("loved", [])
        # Unique sort
        unique = {i["_id"]: i for i in items}
        sorted_recent = sorted(unique.values(), key=lambda x: x.get("_mtime", ""), reverse=True)[:50]

        scored = [self.scoring.process_item(i) for i in sorted_recent]

        if not scored:
            # Fallback to trending
            return await self._get_trending_fallback(content_type, max_results)

        profile = await self.user_profile.build_user_profile(scored, content_type=content_type)

        # 2. Discover
        candidates = await self.discovery.discover_recommendations(
            profile,
            content_type,
            limit=max_results * 2,
            use_genres=True,
            use_keywords=True,
            use_cast=False,  # Simplify for speed
        )

        watched_imdb, watched_tmdb = await self.filter_engine.get_exclusion_sets()
        valid_candidates = [c for c in candidates if c["id"] not in watched_tmdb]

        return await self._fetch_and_format(valid_candidates, content_type, watched_imdb, limit=max_results)

    async def _get_trending_fallback(self, content_type, limit):
        trending = await self.tmdb.get_trending(content_type)
        candidates = trending.get("results", []) if trending else []
        watched_imdb, watched_tmdb = await self.filter_engine.get_exclusion_sets()
        valid = [c for c in candidates if c["id"] not in watched_tmdb]
        return await self._fetch_and_format(valid, content_type, watched_imdb, limit=limit)

    async def pad_to_min(self, content_type: str, existing: list[dict], min_items: int) -> list[dict]:
        if len(existing) >= min_items:
            return existing

        needed = min_items - len(existing)

        trending = await self.tmdb.get_trending(content_type)
        candidates = trending.get("results", []) if trending else []

        watched_imdb, watched_tmdb = await self.filter_engine.get_exclusion_sets()

        existing_ids = {x.get("id") for x in existing}

        valid_candidates = []
        for c in candidates:
            if c["id"] in watched_tmdb:
                continue
            valid_candidates.append(c)

        extra_items = await self._fetch_and_format(valid_candidates, content_type, watched_imdb, limit=needed * 2)

        final = list(existing)
        count = 0
        for item in extra_items:
            if item["id"] not in existing_ids:
                final.append(item)
                existing_ids.add(item["id"])
                count += 1
                if len(final) >= min_items:
                    break

        return final

    async def _fetch_and_format(self, candidates, media_type, watched_imdb, limit=20):
        final_items = []
        sem = asyncio.Semaphore(10)

        async def _process(c):
            async with sem:
                details = await self.fetcher.fetch_item_details(c["id"], media_type)
                return self.fetcher.format_for_stremio(details, media_type)

        target_candidates = candidates[: max(limit * 2, 40)]

        processed = await asyncio.gather(*[_process(c) for c in target_candidates])

        for item in processed:
            if not item:
                continue
            if item.get("_imdb_id") in watched_imdb:
                continue

            final_items.append(item)
            if len(final_items) >= limit:
                break

        return final_items
