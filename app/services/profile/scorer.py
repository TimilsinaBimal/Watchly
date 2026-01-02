from typing import Any

from app.models.taste_profile import TasteProfile
from app.services.profile.constants import (
    FEATURE_WEIGHT_COUNTRY,
    FEATURE_WEIGHT_CREATOR,
    FEATURE_WEIGHT_ERA,
    FEATURE_WEIGHT_GENRE,
    FEATURE_WEIGHT_KEYWORD,
)


class ProfileScorer:
    """
    Scores items against taste profile using unified function.
    """

    @staticmethod
    def score_item(item_metadata: dict[str, Any], profile: TasteProfile) -> float:
        """
        Score an item against the profile.

        Uses weighted feature matching with proper feature weights.

        Args:
            item_metadata: Item metadata dict with genres, keywords, year, countries, etc.
            profile: TasteProfile to score against

        Returns:
            Score (higher = better match)
        """
        # Normalize profile for ranking (read-time only)
        normalized = profile.normalize_for_ranking()

        score = 0.0

        # Genre score (weighted average of matching genres)
        item_genres = item_metadata.get("genre_ids", [])
        if item_genres:
            genre_matches = [normalized["genres"].get(gid, 0.0) for gid in item_genres]
            genre_score = sum(genre_matches) / len(genre_matches) if genre_matches else 0.0
            score += genre_score * FEATURE_WEIGHT_GENRE

        # Keyword score (weighted average of matching keywords)
        item_keywords = item_metadata.get("keyword_ids", [])
        if not item_keywords:
            # Try to extract from keywords dict
            keywords = item_metadata.get("keywords", {})
            if isinstance(keywords, dict):
                item_keywords = [k.get("id") for k in keywords.get("keywords", []) if k.get("id")]

        if item_keywords:
            keyword_matches = [normalized["keywords"].get(kid, 0.0) for kid in item_keywords]
            keyword_score = sum(keyword_matches) / len(keyword_matches) if keyword_matches else 0.0
            score += keyword_score * FEATURE_WEIGHT_KEYWORD

        # Cast score (weighted average of matching cast)
        item_cast = ProfileScorer._extract_cast_ids(item_metadata)
        if item_cast:
            cast_matches = [normalized["cast"].get(cid, 0.0) for cid in item_cast]
            cast_score = sum(cast_matches) / len(cast_matches) if cast_matches else 0.0
            score += cast_score * FEATURE_WEIGHT_CREATOR

        # Director score (weighted average of matching directors)
        item_directors = ProfileScorer._extract_director_ids(item_metadata)
        if item_directors:
            director_matches = [normalized["directors"].get(did, 0.0) for did in item_directors]
            director_score = sum(director_matches) / len(director_matches) if director_matches else 0.0
            score += director_score * FEATURE_WEIGHT_CREATOR

        # Era score
        year = item_metadata.get("release_date") or item_metadata.get("first_air_date")
        if year:
            try:
                year_int = int(str(year)[:4])
                era = ProfileScorer._year_to_era(year_int)
                era_score = normalized["eras"].get(era, 0.0)
                score += era_score * FEATURE_WEIGHT_ERA
            except (ValueError, TypeError):
                pass

        # Country score (weighted average of matching countries)
        item_countries = ProfileScorer._extract_country_codes(item_metadata)
        if item_countries:
            country_matches = [normalized["countries"].get(cc, 0.0) for cc in item_countries]
            country_score = sum(country_matches) / len(country_matches) if country_matches else 0.0
            score += country_score * FEATURE_WEIGHT_COUNTRY

        return score

    @staticmethod
    def _extract_cast_ids(item_metadata: dict[str, Any]) -> list[int]:
        """Extract cast IDs from item metadata."""
        cast_ids = []
        credits = item_metadata.get("credits", {}) or {}
        cast_list = credits.get("cast", []) or []
        for actor in cast_list[:5]:  # Top 5 only
            if isinstance(actor, dict):
                actor_id = actor.get("id")
                if actor_id:
                    cast_ids.append(actor_id)
        return cast_ids

    @staticmethod
    def _extract_director_ids(item_metadata: dict[str, Any]) -> list[int]:
        """Extract director IDs from item metadata."""
        director_ids = []
        credits = item_metadata.get("credits", {}) or {}
        crew_list = credits.get("crew", []) or []
        for crew_member in crew_list:
            if isinstance(crew_member, dict) and crew_member.get("job") == "Director":
                director_id = crew_member.get("id")
                if director_id:
                    director_ids.append(director_id)
        return director_ids

    @staticmethod
    def _extract_country_codes(item_metadata: dict[str, Any]) -> list[str]:
        """Extract country codes from item metadata."""
        countries = []
        production_countries = item_metadata.get("production_countries", []) or []
        for country in production_countries:
            if isinstance(country, dict):
                country_code = country.get("iso_3166_1")
            else:
                country_code = country
            if country_code:
                countries.append(country_code)
        return countries

    @staticmethod
    def _year_to_era(year: int) -> str:
        """Convert year to era bucket."""
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
