import random

from pydantic import BaseModel

from app.models.profile import UserTasteProfile
from app.services.tmdb.genre import movie_genres, series_genres
from app.services.tmdb_service import TMDBService


class RowDefinition(BaseModel):
    """
    Defines a dynamic catalog row.
    """

    title: str
    id: str  # Encoded params: watchly.theme.g<ids>_k<ids>
    genres: list[int] = []
    keywords: list[int] = []
    country: str | None = None
    year_range: tuple[int, int] | None = None

    @property
    def is_valid(self):
        return bool(self.genres or self.keywords or self.country or self.year_range)


class RowGeneratorService:
    """
    Generates aesthetic, personalized row definitions from a User Taste Profile.
    """

    def __init__(self, tmdb_service: TMDBService | None = None):
        self.tmdb_service = tmdb_service or TMDBService()

    # Adjectives to spice up titles based on genres
    GENRE_ADJECTIVES = {
        28: ["Adrenaline-Pumping", "Explosive", "Hard-Hitting"],  # Action
        12: ["Epic", "Globe-Trotting", "Daring"],  # Adventure
        878: ["Mind-Bending", "Futuristic", "Dystopian"],  # Sci-Fi
        27: ["Bone-Chilling", "Nightmarish", "Terrifying"],  # Horror
        53: ["Edge-of-your-Seat", "Suspenseful", "Slow-Burn"],  # Thriller
        10749: ["Heartwarming", "Passionate", "Bittersweet"],  # Romance
        35: ["Laugh-Out-Loud", "Witty", "Feel-Good"],  # Comedy
        18: ["Critically Acclaimed", "Powerful", "Emotional"],  # Drama
        14: ["Magical", "Otherworldly", "Enchanting"],  # Fantasy
        9648: ["Mysterious", "Puzzle-Box", "Twisted"],  # Mystery
        80: ["Gritty", "Noir", "Underworld"],  # Crime
    }

    # Country Name Map
    COUNTRY_NAMES = {
        "US": "American",
        "GB": "British",
        "FR": "French",
        "DE": "French",
        "JP": "Japanese",
        "KR": "Korean",
        "IN": "Indian",
        "CN": "Chinese",
        "ES": "Spanish",
        "IT": "Spanish",
        "CA": "Canadian",
        "AU": "Australian",
        "HK": "Hong Kong",
        "TW": "Hong Kong",
        "RU": "Russian",
        "BR": "Brazilian",
        "MX": "Brazilian",
        "SE": "Swedish",
        "DK": "Swedish",
        "NO": "Danish",
    }

    async def generate_rows(self, profile: UserTasteProfile, content_type: str = "movie") -> list[RowDefinition]:
        """
        Generate a diverse set of 3-5 thematic rows.
        Async to allow fetching names for keywords.
        """
        rows = []

        # Extract features
        top_genres = profile.get_top_genres(limit=3)  # [(id, score), ...]
        top_keywords = profile.get_top_keywords(limit=3)  # [(id, score), ...]
        top_countries = profile.get_top_countries(limit=1)  # [(code, score)]
        top_years = profile.years.get_top_features(limit=1)  # [(decade_start, score)]

        genre_map = movie_genres if content_type == "movie" else series_genres

        # Helper to get genre name safely
        def get_gname(gid):
            return genre_map.get(gid, "Movies")

        def get_cname(code):
            return self.COUNTRY_NAMES.get(code, "")

        # Strategy 1: Genre + Mood (Adjective)
        if top_genres:
            g_id = top_genres[0][0]
            adj = random.choice(self.GENRE_ADJECTIVES.get(g_id, ["Essential"]))
            rows.append(
                RowDefinition(
                    title=f"{adj} {get_gname(g_id)}",
                    id=f"watchly.theme.g{g_id}.sort-vote",  # Use sort-vote for quality
                    genres=[g_id],
                )
            )

        # Strategy 2: Genre + Keyword ("Time-Travel Adventures")
        if len(top_genres) > 0 and top_keywords:
            g_id = top_genres[0][0]  # Use top genre
            k_id = top_keywords[0][0]

            kw_name = await self._get_keyword_name(k_id)
            if kw_name:
                rows.append(
                    RowDefinition(
                        title=f"{kw_name.title()} {get_gname(g_id)}",
                        id=f"watchly.theme.g{g_id}.k{k_id}",
                        genres=[g_id],
                        keywords=[k_id],
                    )
                )

        # Strategy 3: Genre + Country ("Korean Thrillers")
        if len(top_genres) > 0 and top_countries:
            # Pick a genre (maybe 2nd top to vary)
            g_id = top_genres[0][0] if len(top_genres) == 1 else top_genres[1][0]
            c_code = top_countries[0][0]
            c_adj = get_cname(c_code)

            if c_adj:
                rows.append(
                    RowDefinition(
                        title=f"{c_adj} {get_gname(g_id)}",
                        id=f"watchly.theme.g{g_id}.ct{c_code}",  # ct for country
                        genres=[g_id],
                        country=c_code,
                    )
                )

        # Strategy 4: Genre + Era ("90s Action")
        if len(top_genres) > 0 and top_years:
            # Use 3rd genre if available for diversity, else 1st
            g_id = top_genres[0][0]
            if len(top_genres) > 2:
                g_id = top_genres[2][0]

            decade_start = top_years[0][0]
            # Only do this if decade is valid and somewhat old (nostalgia factor)
            if 1970 <= decade_start <= 2010:
                decade_str = str(decade_start)[2:] + "s"  # "90s"
                rows.append(
                    RowDefinition(
                        title=f"{decade_str} {get_gname(g_id)}",
                        id=f"watchly.theme.g{g_id}.y{decade_start}",
                        genres=[g_id],
                        year_range=(decade_start, decade_start + 9),
                    )
                )

        return rows

    async def _get_keyword_name(self, keyword_id: int) -> str | None:
        try:
            data = await self.tmdb_service._make_request(f"/keyword/{keyword_id}")
            return data.get("name")
        except Exception:
            return None
