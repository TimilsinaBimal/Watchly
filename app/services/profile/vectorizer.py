from typing import Any

from app.models.scoring import ScoredItem
from app.services.profile.constants import CAST_POSITION_LEAD, CAST_POSITION_MINOR, CAST_POSITION_SUPPORTING


class ProfileVectorizer:
    """
    Legacy vectorizer for extracting features from TMDB metadata.
    Used by old profile service and similarity calculations.
    """

    @staticmethod
    def vectorize_item(metadata: dict[str, Any]) -> dict[str, Any] | None:
        """
        Extract features from TMDB metadata.

        Args:
            metadata: TMDB metadata dict

        Returns:
            Dictionary with extracted features or None
        """
        if not metadata:
            return None

        # Extract genres
        genres = [g.get("id") for g in metadata.get("genres", []) if g.get("id")]

        # Extract keywords
        keywords = [k.get("id") for k in metadata.get("keywords", {}).get("keywords", []) if k.get("id")]

        # Extract cast (top 10)
        cast = []
        credits = metadata.get("credits", {}) or {}
        cast_list = credits.get("cast", []) or []
        for idx, actor in enumerate(cast_list[:10]):
            actor_id = actor.get("id") if isinstance(actor, dict) else actor
            if actor_id:
                cast.append(actor_id)

        # Extract countries
        countries = []
        production_countries = metadata.get("production_countries", []) or []
        for country in production_countries:
            country_code = country.get("iso_3166_1") if isinstance(country, dict) else country
            if country_code:
                countries.append(country_code)

        # Extract year
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
    """
    Extracts features from items for taste profile building.

    Pure extraction: no scoring, no accumulation, just feature extraction.
    """

    def __init__(self, tmdb_service: Any):
        """
        Initialize vectorizer.

        Args:
            tmdb_service: TMDB service for fetching metadata
        """
        self.tmdb_service = tmdb_service

    async def extract_features(self, item: ScoredItem) -> dict[str, Any] | None:
        """
        Extract all features from an item.

        Args:
            item: ScoredItem to extract features from

        Returns:
            Dictionary with extracted features, or None if extraction fails
        """
        try:
            # Resolve TMDB ID
            tmdb_id = await self._resolve_tmdb_id(item.item.id)
            if not tmdb_id:
                return None

            # Fetch metadata
            if item.item.type == "movie":
                metadata = await self.tmdb_service.get_movie_details(tmdb_id)
            else:
                metadata = await self.tmdb_service.get_tv_details(tmdb_id)

            if not metadata:
                return None

            # Extract features using legacy vectorizer (reuse existing logic)
            vector = ProfileVectorizer.vectorize_item(metadata)
            if not vector:
                return None

            # Transform to our format (pass metadata for crew job extraction)
            return self._transform_vector(vector, metadata)

        except Exception as e:
            from loguru import logger

            logger.exception(f"Failed to extract features from item {item.item.id}: {e}")
            return None

    def _transform_vector(self, vector: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
        """
        Transform legacy vector format to our feature format.

        Args:
            vector: Legacy vector format
            metadata: Full metadata for additional extraction

        Returns:
            Transformed feature dictionary
        """
        features = {
            "genres": vector.get("genres", []),
            "keywords": vector.get("keywords", []),
            "cast": self._extract_cast_with_positions(vector.get("cast", [])),
            "crew": self._extract_crew_with_jobs(metadata),
            "countries": vector.get("countries", []),
            "year": vector.get("year"),
        }

        # Extract era bucket from year
        if features["year"]:
            features["era"] = self._year_to_era(features["year"])

        return features

    def _extract_cast_with_positions(self, cast: list[Any]) -> list[dict[str, Any]]:
        """
        Extract cast with position weights.

        Args:
            cast: Cast list (can be list of IDs or list of dicts)

        Returns:
            List of cast dicts with position and weight
        """
        if not cast:
            return []

        result = []
        for idx, cast_item in enumerate(cast[:10]):  # Top 10 only
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
        """
        Get weight for cast position.

        Args:
            position: Cast position (0 = lead, higher = supporting)

        Returns:
            Position weight
        """
        if position == 0:
            return CAST_POSITION_LEAD
        elif position < 3:
            return CAST_POSITION_SUPPORTING
        else:
            return CAST_POSITION_MINOR

    def _extract_crew_with_jobs(self, metadata: dict[str, Any]) -> list[dict[str, Any]]:
        """
        Extract crew with job information.

        Args:
            metadata: Full metadata dict with credits

        Returns:
            List of crew dicts with id and job
        """
        crew_list = []
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
    def _year_to_era(year: int) -> str:
        """
        Convert year to era bucket.

        Args:
            year: Release year

        Returns:
            Era bucket string (e.g., "1990s", "2010s")
        """
        if year < 1970:
            return "pre-1970s"
        elif year < 1980:
            return "1970s"
        elif year < 1990:
            return "1980s"
        elif year < 2000:
            return "1990s"
        elif year < 2010:
            return "2000s"
        elif year < 2020:
            return "2010s"
        else:
            return "2020s"

    async def _resolve_tmdb_id(self, stremio_id: str) -> int | None:
        """
        Resolve Stremio ID to TMDB ID.

        Args:
            stremio_id: Stremio item ID

        Returns:
            TMDB ID or None
        """
        if stremio_id.startswith("tmdb:"):
            try:
                return int(stremio_id.split(":")[1])
            except (ValueError, IndexError):
                return None
        elif stremio_id.startswith("tt"):
            tmdb_id, _ = await self.tmdb_service.find_by_imdb_id(stremio_id)
            return tmdb_id
        else:
            try:
                return int(stremio_id)
            except ValueError:
                return None
