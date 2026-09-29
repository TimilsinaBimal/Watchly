import asyncio
import random
from datetime import datetime, timedelta, timezone
from typing import Any

from loguru import logger

from app.core.constants import DEFAULT_CATALOG_LIMIT
from app.core.settings import UserSettings
from app.models.library import LibraryCollection
from app.models.profile import TasteProfile
from app.services.profile.sampling import sample_items
from app.services.profile.scorer import ProfileScorer
from app.services.profile.scoring import ScoringService
from app.services.recommendation.filtering import RecommendationFiltering
from app.services.recommendation.metadata import RecommendationMetadata
from app.services.recommendation.scoring import RecommendationScoring
from app.services.recommendation.utils import content_type_to_mtype, resolve_tmdb_id
from app.services.tmdb.service import TMDBService

COOLDOWN = timedelta(days=180)
# Drawn from the highest-signal items so the detail fetches mostly hit what the
# profile build already cached.
POOL_SIZE = 50
REACTION_BOOST = {"loved": 1.2, "liked": 1.1, "watched": 1.0}


class RewatchService:
    """Titles the user has already watched, ranked by how well they fit the taste profile."""

    def __init__(self, tmdb_service: TMDBService, user_settings: UserSettings):
        self.tmdb_service = tmdb_service
        self.user_settings = user_settings
        self.scorer = ProfileScorer()

    async def get_rewatch_picks(
        self,
        library_items: LibraryCollection,
        content_type: str,
        profile: TasteProfile | None,
        limit: int = DEFAULT_CATALOG_LIMIT,
    ) -> list[dict[str, Any]]:
        typed = library_items.for_type(content_type)
        cutoff = datetime.now(timezone.utc) - COOLDOWN

        def cooled(items):
            kept = []
            for i in items:
                last = i.state.lastWatched
                # Stremio timestamps without an offset parse naive; treat them as UTC.
                if not last or last.replace(tzinfo=last.tzinfo or timezone.utc) < cutoff:
                    kept.append(i)
            return kept

        pool = LibraryCollection(
            loved=cooled(typed.loved), liked=cooled(typed.liked), watched=cooled(typed.watched), source=typed.source
        )
        if pool.is_empty():
            # Everything was watched recently; a row of recent titles beats a blank shelf.
            logger.info(f"All {content_type} history is inside the rewatch cooldown, ignoring it")
            pool = LibraryCollection(loved=typed.loved, liked=typed.liked, watched=typed.watched, source=typed.source)

        sampled = sample_items(pool, content_type, ScoringService(), max_items=POOL_SIZE)
        if not sampled:
            return []

        mtype = content_type_to_mtype(content_type)
        tmdb_ids = await asyncio.gather(*(resolve_tmdb_id(s.item.id, self.tmdb_service) for s in sampled))
        fetch = self.tmdb_service.get_movie_details if mtype == "movie" else self.tmdb_service.get_tv_details
        resolved = [(s, tid) for s, tid in zip(sampled, tmdb_ids) if tid]
        details_list = await asyncio.gather(*(fetch(tid) for _, tid in resolved), return_exceptions=True)

        failed = sum(1 for d in details_list if isinstance(d, Exception))
        if failed:
            logger.warning(f"Rewatch: {failed}/{len(resolved)} {content_type} detail fetches failed, skipping them")

        excluded = set(RecommendationFiltering.get_excluded_genre_ids(self.user_settings, content_type))
        scored: list[tuple[float, dict[str, Any]]] = []
        for (sampled_item, _), details in zip(resolved, details_list):
            if isinstance(details, Exception) or not details:
                continue
            # A copy: the details dict is the alru_cache entry. Full details carry
            # `genres`, the scorer reads `genre_ids`.
            item = {**details, "genre_ids": [g["id"] for g in details.get("genres", [])]}
            if excluded.intersection(item["genre_ids"]):
                continue
            if profile:
                score = RecommendationScoring.calculate_final_score(item, profile, self.scorer, mtype)
            else:
                score = sampled_item.score
            scored.append((score * REACTION_BOOST[sampled_item.source_type], item))

        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[: limit * 2]
        picked = sorted(random.sample(top, k=min(limit, len(top))), key=lambda x: x[0], reverse=True)

        return await RecommendationMetadata.fetch_batch(
            self.tmdb_service, [item for _, item in picked], content_type, user_settings=self.user_settings
        )
