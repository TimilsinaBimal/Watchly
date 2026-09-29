from typing import Any

import httpx
from loguru import logger

from app.models.profile import ScoredItem
from app.services.cinemeta_service import CinemetaService, cinemeta_service
from app.services.profile.constants import (
    CAST_POSITION_LEAD,
    CAST_POSITION_MINOR,
    RUNTIME_BUCKET_MEDIUM_MAX_MOVIE,
    RUNTIME_BUCKET_MEDIUM_MAX_SERIES,
    RUNTIME_BUCKET_SHORT_MAX_MOVIE,
    RUNTIME_BUCKET_SHORT_MAX_SERIES,
)
from app.services.recommendation.utils import resolve_tmdb_id, year_to_era
from app.services.tmdb.service import TMDBService


class ProfileVectorizer:
    """Extracts raw feature ids from TMDB metadata."""

    @staticmethod
    def vectorize_item(metadata: dict[str, Any]) -> dict[str, Any] | None:
        if not metadata:
            return None

        genres = [g.get("id") for g in metadata.get("genres", []) if g.get("id")]

        keywords_dict = metadata.get("keywords")
        if isinstance(keywords_dict, dict):
            keywords = keywords_dict.get("results", [])  # for series
            if not keywords:
                keywords = keywords_dict.get("keywords", [])  # for movies
        else:
            keywords = keywords_dict

        keywords = [k.get("id") for k in keywords if k.get("id")]

        # Top 3 cast only — main + two critical supporting. Tracking deeper into
        # the credit list pollutes "favorite cast" with bit-part actors who
        # happen to appear across many genre films but who the user wasn't
        # actually drawn to. CreatorsService pairs this with a freq>=2 filter.
        cast = []
        credits = metadata.get("credits", {}) or {}
        cast_list = credits.get("cast", []) or []
        for idx, actor in enumerate(cast_list[:3]):
            actor_id = actor.get("id") if isinstance(actor, dict) else actor
            if actor_id:
                cast.append(actor_id)

        countries = []
        production_countries = metadata.get("production_countries", []) or []
        for country in production_countries:
            country_code = country.get("iso_3166_1") if isinstance(country, dict) else country
            if country_code:
                countries.append(country_code)

        release_date = metadata.get("release_date") or metadata.get("first_air_date")
        year = None
        if release_date:
            try:
                year = int(release_date.split("-")[0])
            except (ValueError, AttributeError):
                pass

        return {
            "genres": genres,
            "keywords": keywords,
            "cast": cast,
            "countries": countries,
            "year": year,
        }


class ItemVectorizer:
    """Extracts features from items for taste profile building; no scoring or accumulation."""

    def __init__(self, tmdb_service: TMDBService):
        self.tmdb_service = tmdb_service
        self.cinemeta_service: CinemetaService = cinemeta_service

    async def extract_features(self, item: ScoredItem) -> dict[str, Any] | None:
        try:
            tmdb_id = await resolve_tmdb_id(item.item.id, self.tmdb_service)
            if not tmdb_id:
                return None

            if item.item.type == "movie":
                metadata = await self.tmdb_service.get_movie_details(tmdb_id)
            else:
                metadata = await self.tmdb_service.get_tv_details(tmdb_id)

            if not metadata:
                return None

            vector = ProfileVectorizer.vectorize_item(metadata)
            if not vector:
                return None

            return await self._transform_vector(vector, metadata, item.item.type)

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.debug(f"TMDB not found ({e.response.status_code}) for item {item.item.id}, skipping")
            else:
                logger.warning(f"TMDB error {e.response.status_code} for item {item.item.id}")
            return None
        except Exception as e:
            logger.warning(f"Failed to extract features from item {item.item.id}: {type(e).__name__}")
            return None

    async def _transform_vector(
        self, vector: dict[str, Any], metadata: dict[str, Any], content_type: str
    ) -> dict[str, Any]:
        features = {
            "genres": vector.get("genres", []),
            "keywords": vector.get("keywords", []),
            "cast": self._extract_cast_with_positions(vector.get("cast", [])),
            "crew": self._extract_crew_with_jobs(metadata),
            "countries": vector.get("countries", []),
            "year": vector.get("year"),
        }

        if features["year"]:
            features["era"] = year_to_era(features["year"])

        imdb_id = metadata.get("external_ids", {}).get("imdb_id")
        cinemeta_metadata = await self.cinemeta_service.get_metadata(imdb_id, content_type) if imdb_id else {}

        runtime_bucket = self._extract_runtime_bucket(cinemeta_metadata)
        if runtime_bucket:
            features["runtime_bucket"] = runtime_bucket

        return features

    def _extract_cast_with_positions(self, cast: list[Any]) -> list[dict[str, Any]]:
        if not cast:
            return []

        result = []
        for idx, cast_item in enumerate(cast[:3]):  # Top 3 — leads only
            if isinstance(cast_item, dict):
                cast_id = cast_item.get("id")
                position = cast_item.get("position", idx)
                weight = cast_item.get("weight", self._get_position_weight(position))
            else:
                cast_id = cast_item
                position = idx
                weight = self._get_position_weight(position)

            if cast_id:
                result.append({"id": cast_id, "position": position, "weight": weight})

        return result

    @staticmethod
    def _get_position_weight(position: int) -> float:
        # Use a decremental (not step-wise) formula for cast position weight, e.g., exponential decay
        # Lead (position 0) is 1.0, next: base**position, with minimum clamp at CAST_POSITION_MINOR.
        BASE = 0.7  # Chosen for smooth, decremental decay
        weight = CAST_POSITION_LEAD * (BASE**position)
        return max(weight, CAST_POSITION_MINOR)

    def _extract_crew_with_jobs(self, metadata: dict[str, Any]) -> list[dict[str, Any]]:
        crew_list = []
        created_by = metadata.get("created_by", []) or []
        if created_by:
            for creator in created_by:
                if isinstance(creator, dict):
                    creator_id = creator.get("id")
                    if creator_id:
                        crew_list.append({"id": creator_id, "job": "Creator"})

        credits = metadata.get("credits", {}) or {}
        crew = credits.get("crew", []) or []

        for crew_member in crew:
            if not isinstance(crew_member, dict):
                continue

            crew_id = crew_member.get("id")
            job = crew_member.get("job", "")

            if crew_id:
                crew_list.append({"id": crew_id, "job": job})

        return crew_list

    @staticmethod
    def _extract_runtime_bucket(cinemeta_metadata: dict[str, Any]) -> str | None:
        content_type = cinemeta_metadata.get("type")
        try:
            runtime = int(str(cinemeta_metadata.get("runtime") or "0").split(" ")[0])
        except ValueError:
            return None
        if not runtime:
            return None

        short_runtime_max = (
            RUNTIME_BUCKET_SHORT_MAX_MOVIE if content_type == "movie" else RUNTIME_BUCKET_SHORT_MAX_SERIES
        )
        medium_runtime_max = (
            RUNTIME_BUCKET_MEDIUM_MAX_MOVIE if content_type == "movie" else RUNTIME_BUCKET_MEDIUM_MAX_SERIES
        )

        if runtime < short_runtime_max:
            return "short"
        elif runtime < medium_runtime_max:
            return "medium"
        else:
            return "long"
