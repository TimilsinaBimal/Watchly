from app.core.settings import UserSettings
from app.services.recommendation.engine import RecommendationEngine
from app.services.stremio_service import StremioService


class RecommendationService:
    """
    Proxy class for backward compatibility.
    Delegates all calls to the modular RecommendationEngine.
    """

    def __init__(
        self,
        stremio_service: StremioService | None = None,
        language: str = "en-US",
        user_settings: UserSettings | None = None,
        token: str | None = None,
        library_data: dict | None = None,
    ):
        if stremio_service is None:
            raise ValueError("StremioService instance is required for personalized recommendations")

        self._engine = RecommendationEngine(
            stremio_service=stremio_service,
            language=language,
            user_settings=user_settings,
            token=token,
            library_data=library_data,
        )

    async def get_recommendations(
        self,
        content_type: str | None = None,
        source_items_limit: int = 5,
        max_results: int = 20,
    ) -> list[dict]:
        if not content_type:
            return []
        return await self._engine.get_recommendations(
            content_type=content_type, source_items_limit=source_items_limit, max_results=max_results
        )

    async def get_recommendations_for_item(self, item_id: str) -> list[dict]:
        """
        Get recommendations for a specific item by identifier.
        """
        return await self._engine.get_recommendations_for_item(item_id)

    async def get_recommendations_for_theme(self, theme_id: str, content_type: str, limit: int = 20) -> list[dict]:
        """
        Fetch recommendations for a dynamic theme.
        """
        return await self._engine.get_recommendations_for_theme(theme_id, content_type, limit)

    async def pad_to_min(self, content_type: str, existing: list[dict], min_items: int) -> list[dict]:
        """
        Pad results with trending/top-rated items.
        """
        return await self._engine.pad_to_min(content_type, existing, min_items)
