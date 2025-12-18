import asyncio

from app.models.profile import UserTasteProfile
from app.services.tmdb import get_tmdb_service


class QueryBuilder:
    """Helper to construct TMDB discovery queries."""

    @staticmethod
    def build_genre_query(genres: list, base_params: dict):
        if not genres:
            return []
        ids = "|".join([str(g[0]) for g in genres])
        return [
            {**base_params, "with_genres": ids, "sort_by": "popularity.desc", "vote_count.gte": 500},
            {**base_params, "with_genres": ids, "sort_by": "vote_average.desc", "vote_count.gte": 500},
        ]

    @staticmethod
    def build_keyword_query(keywords: list, base_params: dict):
        if not keywords:
            return []
        ids = "|".join([str(k[0]) for k in keywords])
        queries = [{**base_params, "with_keywords": ids, "sort_by": "popularity.desc", "vote_count.gte": 500}]
        for page in range(1, 3):
            queries.append(
                {
                    **base_params,
                    "with_keywords": ids,
                    "sort_by": "vote_average.desc",
                    "vote_count.gte": 500,
                    "page": page,
                }
            )
        return queries

    @staticmethod
    def build_cast_query(cast: list, base_params: dict):
        queries = []
        for actor in cast:
            queries.append(
                {**base_params, "with_cast": str(actor[0]), "sort_by": "popularity.desc", "vote_count.gte": 500}
            )
        return queries

    @staticmethod
    def build_director_query(crew: list, base_params: dict):
        if not crew:
            return []
        return [{**base_params, "with_crew": str(crew[0][0]), "sort_by": "vote_average.desc", "vote_count.gte": 500}]

    @staticmethod
    def build_country_query(countries: list, base_params: dict):
        if not countries:
            return []
        ids = "|".join([str(c[0]) for c in countries])
        return [{**base_params, "with_origin_country": ids, "sort_by": "popularity.desc", "vote_count.gte": 100}]

    @staticmethod
    def build_year_query(years: list, base_params: dict):
        if not years:
            return []
        year = years[0][0]
        return [
            {
                **base_params,
                "primary_release_date.gte": f"{year}-01-01",
                "primary_release_date.lte": f"{int(year) + 9}-12-31",
                "sort_by": "vote_average.desc",
                "vote_count.gte": 500,
            }
        ]


class DiscoveryEngine:
    """
    Service to discover content based on User Taste Profile.
    """

    def __init__(self, language: str = "en-US"):
        self.tmdb_service = get_tmdb_service(language=language)
        self._sem = asyncio.Semaphore(10)

    async def discover_recommendations(
        self,
        profile: UserTasteProfile,
        content_type: str,
        limit: int = 20,
        excluded_genres: list[int] | None = None,
        *,
        use_genres: bool = False,
        use_keywords: bool = True,
        use_cast: bool = True,
        use_director: bool = True,
        use_countries: bool = False,
        use_year: bool = False,
    ) -> list[dict]:

        # 1. Extract Top Features
        top_genres = profile.get_top_genres(limit=3) if use_genres else []
        top_keywords = profile.get_top_keywords(limit=3) if use_keywords else []
        top_cast = profile.cast.get_top_features(limit=2) if use_cast else []
        top_crew = profile.get_top_crew(limit=1) if use_director else []
        top_countries = profile.get_top_countries(limit=2) if use_countries else []
        top_year = profile.get_top_year(limit=1) if use_year else []

        if not any([top_genres, top_keywords, top_cast]):
            return []

        base_params = {}
        if excluded_genres:
            base_params["without_genres"] = "|".join([str(g) for g in excluded_genres])

        # 2. Build Queries
        queries = []
        queries.extend(QueryBuilder.build_genre_query(top_genres, base_params))
        queries.extend(QueryBuilder.build_keyword_query(top_keywords, base_params))
        queries.extend(QueryBuilder.build_cast_query(top_cast, base_params))
        queries.extend(QueryBuilder.build_director_query(top_crew, base_params))
        queries.extend(QueryBuilder.build_country_query(top_countries, base_params))
        queries.extend(QueryBuilder.build_year_query(top_year, base_params))

        # 3. Execute Phase 1
        tasks = [self._fetch_discovery(content_type, q) for q in queries]
        results_batches = await asyncio.gather(*tasks, return_exceptions=True)

        # 4. Aggregate
        all_candidates = {}
        for batch in results_batches:
            if isinstance(batch, Exception) or not batch:
                continue
            for item in batch:
                if item["id"] not in all_candidates:
                    all_candidates[item["id"]] = item

        # Conditional Phase 2 (Simplified logic)
        if len(all_candidates) < 120:
            queries2 = []
            # Heuristic: if we have genres/keywords, try page 2 of highest value queries
            if top_genres:
                queries2.append({**QueryBuilder.build_genre_query(top_genres, base_params)[1], "page": 2})
            if top_keywords:
                # Use the rating based one
                queries2.append({**QueryBuilder.build_keyword_query(top_keywords, base_params)[1], "page": 2})

            if queries2:
                tasks2 = [self._fetch_discovery(content_type, q) for q in queries2]
                results2 = await asyncio.gather(*tasks2, return_exceptions=True)
                for batch in results2:
                    if isinstance(batch, dict):  # Should be list, but guard
                        continue
                    if isinstance(batch, Exception) or not batch:
                        continue
                    for item in batch:
                        if item["id"] not in all_candidates:
                            all_candidates[item["id"]] = item

        return list(all_candidates.values())

    async def _fetch_discovery(self, media_type: str, params: dict) -> list[dict]:
        try:
            async with self._sem:
                data = await self.tmdb_service.get_discover(media_type, **params)
                return data.get("results", [])
        except Exception:
            return []
