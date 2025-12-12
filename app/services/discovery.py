import asyncio

from app.models.profile import UserTasteProfile
from app.services.tmdb_service import TMDBService


class DiscoveryEngine:
    """
    Service to discover content based on User Taste Profile.
    Uses TMDB Discovery API with weighted query parameters derived from the user profile.
    """

    def __init__(self):
        self.tmdb_service = TMDBService()
        # Limit concurrent discovery calls to avoid rate limiting
        self._sem = asyncio.Semaphore(10)

    async def discover_recommendations(
        self,
        profile: UserTasteProfile,
        content_type: str,
        limit: int = 20,
        excluded_genres: list[int] | None = None,
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
        top_genres = profile.get_top_genres(limit=3)  # e.g. [(28, 1.0), (878, 0.8)]
        top_keywords = profile.get_top_keywords(limit=3)  # e.g. [(123, 0.9)]
        # Need to add get_top_cast to UserTasteProfile model first, assuming it exists or using profile.cast directly
        # Based on previous step, profile.cast exists.
        top_cast = profile.cast.get_top_features(limit=2)
        top_crew = profile.get_top_crew(limit=1)  # e.g. [(555, 1.0)] - Director

        top_countries = profile.get_top_countries(limit=2)
        top_year = profile.get_top_year(limit=1)

        if not top_genres and not top_keywords and not top_cast:
            # Fallback if profile is empty
            return []

        tasks = []
        base_params = {}
        if excluded_genres:
            base_params["without_genres"] = "|".join([str(g) for g in excluded_genres])

        # Query 1: Top Genres Mix
        if top_genres:
            genre_ids = "|".join([str(g[0]) for g in top_genres])
            params_popular = {
                "with_genres": genre_ids,
                "sort_by": "popularity.desc",
                "vote_count.gte": 500,
                **base_params,
            }
            tasks.append(self._fetch_discovery(content_type, params_popular))

            # fetch atleast two pages of results
            for i in range(2):
                params_rating = {
                    "with_genres": genre_ids,
                    "sort_by": "vote_average.desc",
                    "vote_count.gte": 500,
                    "page": i + 1,
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

            # fetch atleast two pages of results
            for i in range(3):
                params_rating = {
                    "with_keywords": keyword_ids,
                    "sort_by": "vote_average.desc",
                    "vote_count.gte": 500,
                    "page": i + 1,
                    **base_params,
                }
                tasks.append(self._fetch_discovery(content_type, params_rating))

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

            params_rating = {
                "with_cast": str(actor_id),
                "sort_by": "vote_average.desc",
                "vote_count.gte": 500,
                **base_params,
            }
            tasks.append(self._fetch_discovery(content_type, params_rating))

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

            params_rating = {
                "with_crew": str(director_id),
                "sort_by": "vote_average.desc",
                "vote_count.gte": 500,
                **base_params,
            }
            tasks.append(self._fetch_discovery(content_type, params_rating))

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

            params_rating = {
                "with_origin_country": country_ids,
                "sort_by": "vote_average.desc",
                "vote_count.gte": 300,
                **base_params,
            }
            tasks.append(self._fetch_discovery(content_type, params_rating))

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

        # 3. Execute Parallel Queries
        results_batches = await asyncio.gather(*tasks, return_exceptions=True)

        # 4. Aggregate and Deduplicate
        all_candidates = {}
        for batch in results_batches:
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
