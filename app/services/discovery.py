import asyncio

from app.models.profile import UserTasteProfile
from app.services.tmdb_service import get_tmdb_service


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
        """
        Find content that matches the user's taste profile.
        Strategy:
        1. Extract top weighted Genres, Keywords, Actors, Director.
        2. Build specific 'Discovery Queries' for each category.
        3. Fetch results in parallel.
        4. Return the combined candidate set (B).
        """
        # 1. Extract Top Features
        top_genres = profile.get_top_genres(limit=3) if use_genres else []  # e.g. [(28, 1.0), (878, 0.8)]
        top_keywords = profile.get_top_keywords(limit=3) if use_keywords else []  # e.g. [(123, 0.9)]
        # Need to add get_top_cast to UserTasteProfile model first, assuming it exists or using profile.cast directly
        # Based on previous step, profile.cast exists.
        top_cast = profile.cast.get_top_features(limit=2) if use_cast else []
        top_crew = profile.get_top_crew(limit=1) if use_director else []  # e.g. [(555, 1.0)] - Director

        top_countries = profile.get_top_countries(limit=2) if use_countries else []
        top_year = profile.get_top_year(limit=1) if use_year else []

        if not top_genres and not top_keywords and not top_cast:
            # Fallback if profile is empty
            return []

        tasks = []
        base_params = {}
        if excluded_genres:
            base_params["without_genres"] = "|".join([str(g) for g in excluded_genres])

        # Phase 1: build first-page tasks only
        if top_genres:
            genre_ids = "|".join([str(g[0]) for g in top_genres])
            params_popular = {
                "with_genres": genre_ids,
                "sort_by": "popularity.desc",
                "vote_count.gte": 500,
                **base_params,
            }
            tasks.append(self._fetch_discovery(content_type, params_popular))
            params_rating = {
                "with_genres": genre_ids,
                "sort_by": "vote_average.desc",
                "vote_count.gte": 500,
                **base_params,
            }
            tasks.append(self._fetch_discovery(content_type, params_rating))

        # Query 2: Top Keywords
        if top_keywords:
            keyword_ids = "|".join([str(k[0]) for k in top_keywords])
            params_keywords = {
                "with_keywords": keyword_ids,
                "sort_by": "popularity.desc",
                "vote_count.gte": 500,
                **base_params,
            }
            tasks.append(self._fetch_discovery(content_type, params_keywords))

            for page in range(1, 3):
                params_rating_kw = {
                    "with_keywords": keyword_ids,
                    "sort_by": "vote_average.desc",
                    "vote_count.gte": 500,
                    "page": page,
                    **base_params,
                }
                tasks.append(self._fetch_discovery(content_type, params_rating_kw))

        # Query 3: Top Actors
        for actor in top_cast:
            actor_id = actor[0]
            params_actor = {
                "with_cast": str(actor_id),
                "sort_by": "popularity.desc",
                "vote_count.gte": 500,
                **base_params,
            }
            tasks.append(self._fetch_discovery(content_type, params_actor))
            # params_rating = {
            #     "with_cast": str(actor_id),
            #     "sort_by": "vote_average.desc",
            #     "vote_count.gte": 500,
            #     **base_params,
            # }
            # tasks.append(self._fetch_discovery(content_type, params_rating))

        # Query 4: Top Director
        if top_crew:
            director_id = top_crew[0][0]
            params_director = {
                "with_crew": str(director_id),
                "sort_by": "vote_average.desc",  # Directors imply quality preference
                "vote_count.gte": 500,
                **base_params,
            }
            tasks.append(self._fetch_discovery(content_type, params_director))

        # Query 5: Top Countries
        if top_countries:
            country_ids = "|".join([str(c[0]) for c in top_countries])
            params_country = {
                "with_origin_country": country_ids,
                "sort_by": "popularity.desc",
                "vote_count.gte": 100,
                **base_params,
            }
            tasks.append(self._fetch_discovery(content_type, params_country))
            # params_rating = {
            #     "with_origin_country": country_ids,
            #     "sort_by": "vote_average.desc",
            #     "vote_count.gte": 300,
            #     **base_params,
            # }
            # tasks.append(self._fetch_discovery(content_type, params_rating))

        # query 6: Top year
        if top_year:
            year = top_year[0][0]
            # we store year in 10 years bucket
            start_year = f"{year}-01-01"
            end_year = f"{int(year) + 9}-12-31"
            params_rating = {
                "primary_release_date.gte": start_year,
                "primary_release_date.lte": end_year,
                "sort_by": "vote_average.desc",
                "vote_count.gte": 500,
                **base_params,
            }
            tasks.append(self._fetch_discovery(content_type, params_rating))

        # 3. Execute Phase 1
        results_batches = await asyncio.gather(*tasks, return_exceptions=True)

        # 4. Aggregate and Deduplicate
        all_candidates = {}
        for batch in results_batches:
            if isinstance(batch, Exception) or not batch:
                continue
            for item in batch:
                if item["id"] not in all_candidates:
                    all_candidates[item["id"]] = item

        # Conditional Phase 2: fetch page 2 if pool is thin
        if len(all_candidates) < 120:
            tasks2 = []
            if top_genres:
                genre_ids = "|".join([str(g[0]) for g in top_genres])
                tasks2.append(
                    self._fetch_discovery(
                        content_type,
                        {
                            "with_genres": genre_ids,
                            "sort_by": "vote_average.desc",
                            "vote_count.gte": 400,
                            "page": 2,
                            **base_params,
                        },
                    )
                )
            if top_keywords:
                keyword_ids = "|".join([str(k[0]) for k in top_keywords])
                tasks2.append(
                    self._fetch_discovery(
                        content_type,
                        {
                            "with_keywords": keyword_ids,
                            "sort_by": "vote_average.desc",
                            "vote_count.gte": 400,
                            "page": 2,
                            **base_params,
                        },
                    )
                )
            for actor in top_cast[:1]:
                actor_id = actor[0]
                tasks2.append(
                    self._fetch_discovery(
                        content_type,
                        {
                            "with_cast": str(actor_id),
                            "sort_by": "vote_average.desc",
                            "vote_count.gte": 400,
                            "page": 2,
                            **base_params,
                        },
                    )
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

    async def _fetch_discovery(self, media_type: str, params: dict) -> list[dict]:
        """Helper to call TMDB discovery."""
        try:
            async with self._sem:
                data = await self.tmdb_service.get_discover(media_type, **params)
                return data.get("results", [])
        except Exception:
            return []
