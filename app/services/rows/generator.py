import asyncio

from app.models.profile import UserTasteProfile
from app.services.rows.models import RowDefinition
from app.services.rows.strategies.genres import GenreNicheStrategy
from app.services.rows.strategies.keywords import KeywordStrategy
from app.services.rows.strategies.legacy import LegacyStrategy
from app.services.tmdb import TMDBService, get_tmdb_service


class RowGeneratorService:
    """
    Generates aesthetic, personalized row definitions from a User Taste Profile.
    """

    def __init__(self, tmdb_service: TMDBService | None = None):
        self.tmdb_service = tmdb_service or get_tmdb_service()
        self.strategies = [
            KeywordStrategy(self.tmdb_service),
            GenreNicheStrategy(self.tmdb_service),
            LegacyStrategy(self.tmdb_service),
        ]

    async def generate_rows(self, profile: UserTasteProfile, content_type: str = "movie") -> list[RowDefinition]:
        """
        Generate a diverse set of thematic rows.
        Executes all strategies in parallel.
        """

        # Run all strategies concurrently
        tasks = [strategy.generate(profile, content_type) for strategy in self.strategies]

        results = await asyncio.gather(*tasks)

        # Flatten results
        all_rows = []
        for row_list in results:
            if row_list:
                all_rows.extend(row_list)

        return all_rows
