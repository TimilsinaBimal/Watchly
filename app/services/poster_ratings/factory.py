from enum import Enum
from typing import Literal

from app.services.poster_ratings.custom import CustomPosterService
from app.services.poster_ratings.rpdb import RPDBService
from app.services.poster_ratings.top_posters import TopPostersService
from app.services.token_store import token_store


class PosterProvider(Enum):
    RPDB = "rpdb"
    TOP_POSTERS = "top_posters"
    CUSTOM = "custom"


class PosterRatingsFactory:
    def __init__(self):
        self.rpdb_service: RPDBService = RPDBService()
        self.top_posters_service: TopPostersService = TopPostersService()
        self.custom_service: CustomPosterService = CustomPosterService()

    def get_poster_url(
        self,
        poster_provider: PosterProvider,
        api_key: str | None,
        provider: Literal["imdb", "tmdb", "tvdb"],
        item_id: str,
        **kwargs,
    ) -> str | None:

        if api_key and api_key.startswith("gAAAAA"):
            api_key = token_store.decrypt_token(api_key)
            # if still gAAA, decryption failed — keep the original url
            if api_key.startswith("gAAAAA"):
                return kwargs.get("fallback")

        if poster_provider == PosterProvider.CUSTOM:
            # Custom-only kwargs must not flow into the key-based services, which
            # urlencode their kwargs straight into the query string.
            return self.custom_service.get_poster_url(
                url_template=kwargs.get("url_template"),
                imdb_id=item_id if item_id.startswith("tt") else None,
                api_key=api_key,
                language=kwargs.get("language"),
            )

        poster_provider_map = {
            PosterProvider.RPDB: self.rpdb_service,
            PosterProvider.TOP_POSTERS: self.top_posters_service,
        }
        return poster_provider_map[poster_provider].get_poster_url(
            api_key, provider, item_id, fallback=kwargs.get("fallback")
        )


poster_ratings_factory = PosterRatingsFactory()
