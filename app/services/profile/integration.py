from typing import Any

from loguru import logger

from app.models.taste_profile import TasteProfile
from app.services.profile.builder import ProfileBuilder
from app.services.profile.constants import GENRE_WHITELIST_LIMIT
from app.services.profile.sampling import SmartSampler
from app.services.profile.vectorizer import ItemVectorizer
from app.services.recommendation.filtering import RecommendationFiltering
from app.services.scoring import ScoringService
from app.services.tmdb.service import get_tmdb_service


class ProfileIntegration:
    """
    Helper class to integrate taste profile services with existing systems.
    """

    def __init__(self, language: str = "en-US"):
        self.scoring_service = ScoringService()
        self.sampler = SmartSampler(self.scoring_service)
        tmdb_service = get_tmdb_service(language=language)
        vectorizer = ItemVectorizer(tmdb_service)
        self.builder = ProfileBuilder(vectorizer)

    async def build_profile_from_library(
        self,
        library_items: dict,
        content_type: str,
        stremio_service: Any = None,
        auth_key: str | None = None,
    ) -> tuple[TasteProfile | None, set[int], set[str]]:
        """
        Build taste profile from library items and get watched sets.

        Args:
            library_items: Library items dict from Stremio
            content_type: Content type (movie/series)
            stremio_service: Stremio service (optional, for watched sets)
            auth_key: Auth key (optional, for watched sets)

        Returns:
            Tuple of (profile, watched_tmdb, watched_imdb)
        """
        # Get watched sets
        watched_imdb, watched_tmdb = await RecommendationFiltering.get_exclusion_sets(
            stremio_service, library_items, auth_key
        )

        # Convert library items to ScoredItems
        all_items = (
            library_items.get("loved", [])
            + library_items.get("liked", [])
            + library_items.get("watched", [])
            + library_items.get("added", [])
        )
        typed_items = [it for it in all_items if it.get("type") == content_type]

        if not typed_items:
            return None, watched_tmdb, watched_imdb

        # Sample items using SmartSampler (it expects raw library items dict)
        library_items_dict = {
            "loved": [it for it in library_items.get("loved", []) if it.get("type") == content_type],
            "liked": [it for it in library_items.get("liked", []) if it.get("type") == content_type],
            "watched": [it for it in library_items.get("watched", []) if it.get("type") == content_type],
            "added": [it for it in library_items.get("added", []) if it.get("type") == content_type],
        }
        sampled = self.sampler.sample_items(library_items_dict, content_type)

        # Build profile
        profile = await self.builder.build_profile(sampled, content_type=content_type)

        return profile, watched_tmdb, watched_imdb

    async def get_genre_whitelist(
        self,
        profile: TasteProfile,
        content_type: str,
    ) -> set[int]:
        """
        Get genre whitelist from user's top genres in profile.

        Args:
            profile: Taste profile
            content_type: Content type (movie/series)

        Returns:
            Set of top genre IDs
        """
        try:
            if not profile:
                whitelist = set()
            else:
                # Get top genres
                top_genres = profile.get_top_genres(limit=GENRE_WHITELIST_LIMIT)
                whitelist = {int(genre_id) for genre_id, _ in top_genres}
                return whitelist
        except Exception as e:
            logger.warning(f"Failed to build genre whitelist for {content_type}: {e}")
            return set()
