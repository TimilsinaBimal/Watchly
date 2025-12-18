from app.models.profile import UserTasteProfile
from app.models.scoring import ScoredItem
from app.services.profile.service import UserProfileService as ModularUserProfileService

# Global constant used in filtering
TOP_GENRE_WHITELIST_LIMIT = 5


class UserProfileService:
    """
    Proxy class for backward compatibility.
    Delegates all calls to the modular UserProfileService.
    """

    def __init__(self, language: str = "en-US"):
        self._service = ModularUserProfileService(language=language)

    async def build_user_profile(
        self,
        scored_items: list[ScoredItem],
        content_type: str | None = None,
        excluded_genres: list[int] | None = None,
    ) -> UserTasteProfile:
        return await self._service.build_user_profile(scored_items, content_type, excluded_genres)

    def calculate_similarity(self, profile: UserTasteProfile, item_meta: dict) -> float:
        return self._service.calculate_similarity(profile, item_meta)

    def calculate_similarity_with_breakdown(self, profile: UserTasteProfile, item_meta: dict) -> tuple[float, dict]:
        return self._service.calculate_similarity_with_breakdown(profile, item_meta)

    def calculate_simple_overlap_with_breakdown(
        self, profile: UserTasteProfile, item_meta: dict, **kwargs
    ) -> tuple[float, dict]:
        return self._service.calculate_simple_overlap_with_breakdown(profile, item_meta, **kwargs)
