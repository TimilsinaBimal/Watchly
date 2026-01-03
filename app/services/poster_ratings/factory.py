from enum import Enum
from typing import Literal

from app.services.poster_ratings.rpdb import RPDBService
from app.services.poster_ratings.top_posters import TopPostersService


class PosterProvider(Enum):
    RPDB = "rpdb"
    TOP_POSTERS = "top_posters"


class PosterRatingsFactory:
    def __init__(self):
        self.rpdb_service: RPDBService = RPDBService()
        self.top_posters_service: TopPostersService = TopPostersService()

    def get_poster_url(
        self,
        poster_provider: PosterProvider,
        api_key: str,
        provider: Literal["imdb", "tmdb", "tvdb"],
        item_id: str,
        **kwargs,
    ) -> str:

        poster_provider_map = {
            PosterProvider.RPDB: self.rpdb_service,
            PosterProvider.TOP_POSTERS: self.top_posters_service,
        }
        return poster_provider_map[poster_provider].get_poster(api_key, provider, item_id, **kwargs)


poster_ratings_factory = PosterRatingsFactory()
