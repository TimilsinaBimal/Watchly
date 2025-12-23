import asyncio
from typing import Any

from loguru import logger

from app.models.profile import UserTasteProfile
from app.services.tmdb.service import get_tmdb_service


class DiscoveryEngine:
    """
    Service to discover content based on User Taste Profile.
    Uses TMDB Discovery API with weighted query parameters derived from the user profile.
    """

    def __init__(self, language: str = "en-US"):
        self.tmdb_service = get_tmdb_service(language=language)
        # Limit concurrent discovery calls to avoid rate limiting
        self._sem = asyncio.Semaphore(10)

    async def discover_recommendations(
        self,
        profile: UserTasteProfile,
        content_type: str,
        excluded_genres: list[int] | None = None,
        *,
        use_genres: bool = False,
        use_keywords: bool = True,
        use_cast: bool = True,
        use_director: bool = True,
        use_countries: bool = False,
        use_year: bool = False,
    ) -> list[dict]:
        """
        Find content that matches the user's taste profile using multi-phase TMDB discovery.
        """
        # Calculate pages to fetch per query based on excluded genres
        num_excluded = len(excluded_genres) if excluded_genres else 0
        if num_excluded > 10:
            pages_per_query = 5  # Fetch 5 pages when most genres are excluded
        elif num_excluded > 5:
            pages_per_query = 3  # Fetch 3 pages when many genres are excluded
        else:
            pages_per_query = 1  # Default: 1 page

        # 1. Build Phase 1 Tasks
        tasks = self._build_discovery_tasks_phase1(
            profile,
            content_type,
            excluded_genres,
            pages_per_query=pages_per_query,
            use_genres=use_genres,
            use_keywords=use_keywords,
            use_cast=use_cast,
            use_director=use_director,
            use_countries=use_countries,
            use_year=use_year,
        )

        if not tasks:
            return []

        # 2. Execute Phase 1
        results_batches = await asyncio.gather(*tasks, return_exceptions=True)

        # 3. Aggregate Candidates
        all_candidates = {}
        for batch in results_batches:
            if isinstance(batch, Exception) or not batch:
                continue
            for item in batch:
                if item["id"] not in all_candidates:
                    all_candidates[item["id"]] = item

        # 4. Phase 2 (If pool is thin)
        if len(all_candidates) < 120:
            tasks2 = self._build_discovery_tasks_phase2(
                profile,
                content_type,
                excluded_genres,
                pages_per_query=pages_per_query,
                use_genres=use_genres,
                use_keywords=use_keywords,
                use_cast=use_cast,
            )
            if tasks2:
                results_batches2 = await asyncio.gather(*tasks2, return_exceptions=True)
                for batch in results_batches2:
                    if isinstance(batch, Exception) or not batch:
                        continue
                    for item in batch:
                        if item["id"] not in all_candidates:
                            all_candidates[item["id"]] = item

        return list(all_candidates.values())

    def _build_discovery_tasks_phase1(
        self,
        profile: UserTasteProfile,
        content_type: str,
        excluded_genres: list[int] | None = None,
        pages_per_query: int = 1,
        **opts,
    ) -> list[Any]:
        """Construct the initial set of discovery tasks based on top profile features."""
        top_genres = profile.get_top_genres(limit=3) if opts.get("use_genres") else []
        top_keywords = profile.get_top_keywords(limit=3) if opts.get("use_keywords") else []
        top_cast = profile.cast.get_top_features(limit=2) if opts.get("use_cast") else []
        top_crew = profile.get_top_crew(limit=1) if opts.get("use_director") else []
        top_countries = profile.get_top_countries(limit=2) if opts.get("use_countries") else []
        top_year = profile.get_top_year(limit=1) if opts.get("use_year") else []

        if not any([top_genres, top_keywords, top_cast, top_crew]):
            return []

        tasks = []
        base_params = {}
        if excluded_genres:
            base_params["without_genres"] = "|".join([str(g) for g in excluded_genres])

        # Query 1: Top Genres - fetch multiple pages
        if top_genres:
            genre_ids = "|".join([str(g[0]) for g in top_genres])
            for page in range(1, pages_per_query + 1):
                for sort_by_option in ["popularity.desc", "vote_average.desc"]:
                    tasks.append(
                        self._fetch_discovery(
                            content_type,
                            {
                                "with_genres": genre_ids,
                                "sort_by": sort_by_option,
                                "vote_count.gte": 500,
                                "page": page,
                                **base_params,
                            },
                        )
                    )

        # Query 2: Top Keywords - fetch multiple pages
        if top_keywords:
            keyword_ids = "|".join([str(k[0]) for k in top_keywords])
            for page in range(1, pages_per_query + 1):
                tasks.append(
                    self._fetch_discovery(
                        content_type,
                        {
                            "with_keywords": keyword_ids,
                            "sort_by": "popularity.desc",
                            "vote_count.gte": 500,
                            "page": page,
                            **base_params,
                        },
                    )
                )
                tasks.append(
                    self._fetch_discovery(
                        content_type,
                        {
                            "with_keywords": keyword_ids,
                            "sort_by": "vote_average.desc",
                            "vote_count.gte": 500,
                            "page": page,
                            **base_params,
                        },
                    )
                )

        # Query 3: Cast & Crew - fetch multiple pages
        is_tv = content_type in ("tv", "series")
        for actor in top_cast:
            for page in range(1, pages_per_query + 1):
                p = {"sort_by": "popularity.desc", "vote_count.gte": 500, "page": page, **base_params}
                p["with_people" if is_tv else "with_cast"] = str(actor[0])
                tasks.append(self._fetch_discovery(content_type, p))

        if top_crew:
            for page in range(1, pages_per_query + 1):
                p = {"sort_by": "vote_average.desc", "vote_count.gte": 500, "page": page, **base_params}
                p["with_people" if is_tv else "with_crew"] = str(top_crew[0][0])
                tasks.append(self._fetch_discovery(content_type, p))

        # Query 4: Countries & Year - fetch multiple pages
        if top_countries:
            country_ids = "|".join([str(c[0]) for c in top_countries])
            for page in range(1, pages_per_query + 1):
                tasks.append(
                    self._fetch_discovery(
                        content_type,
                        {
                            "with_origin_country": country_ids,
                            "sort_by": "popularity.desc",
                            "vote_count.gte": 100,
                            "page": page,
                            **base_params,
                        },
                    )
                )

        if top_year:
            year = top_year[0][0]
            prefix = "first_air_date" if is_tv else "primary_release_date"
            for page in range(1, pages_per_query + 1):
                tasks.append(
                    self._fetch_discovery(
                        content_type,
                        {
                            "sort_by": "vote_average.desc",
                            "vote_count.gte": 500,
                            f"{prefix}.gte": f"{year}-01-01",
                            f"{prefix}.lte": f"{int(year)+9}-12-31",
                            "page": page,
                            **base_params,
                        },
                    )
                )
        return tasks

    def _build_discovery_tasks_phase2(
        self,
        profile: UserTasteProfile,
        content_type: str,
        excluded_genres: list[int] | None = None,
        pages_per_query: int = 1,
        **opts,
    ) -> list[Any]:
        """Construct additional discovery tasks with lower thresholds to fill out candidate pool."""
        top_genres = profile.get_top_genres(limit=3) if opts.get("use_genres") else []
        top_keywords = profile.get_top_keywords(limit=3) if opts.get("use_keywords") else []
        top_cast = profile.cast.get_top_features(limit=1) if opts.get("use_cast") else []

        tasks = []
        base_params = {"vote_count.gte": 400}
        if excluded_genres:
            base_params["without_genres"] = "|".join([str(g) for g in excluded_genres])

        # Start from page 2 for phase 2, but fetch multiple pages if needed
        start_page = 2
        end_page = start_page + pages_per_query

        if top_genres:
            genre_ids = "|".join([str(g[0]) for g in top_genres])
            for page in range(start_page, end_page):
                tasks.append(
                    self._fetch_discovery(
                        content_type,
                        {"with_genres": genre_ids, "sort_by": "vote_average.desc", "page": page, **base_params},
                    )
                )

        if top_keywords:
            keyword_ids = "|".join([str(k[0]) for k in top_keywords])
            for page in range(start_page, end_page):
                tasks.append(
                    self._fetch_discovery(
                        content_type,
                        {"with_keywords": keyword_ids, "sort_by": "vote_average.desc", "page": page, **base_params},
                    )
                )

        if top_cast:
            actor_id = top_cast[0][0]
            is_tv = content_type in ("tv", "series")
            for page in range(start_page, end_page):
                p = {"sort_by": "vote_average.desc", "page": page, **base_params}
                p["with_people" if is_tv else "with_cast"] = str(actor_id)
                tasks.append(self._fetch_discovery(content_type, p))

        return tasks

    async def _fetch_discovery(self, media_type: str, params: dict) -> list[dict]:
        """Helper to call TMDB discovery."""
        try:
            async with self._sem:
                data = await self.tmdb_service.get_discover(media_type, **params)
                return data.get("results", [])
        except Exception as e:
            logger.exception(f"TMDB Discovery failed with params {params}: {e}")
            return []
