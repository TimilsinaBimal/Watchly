import random

from pydantic import BaseModel

from app.models.profile import UserTasteProfile
from app.services.gemini import gemini_service
from app.services.tmdb.countries import COUNTRY_ADJECTIVES
from app.services.tmdb.genre import movie_genres, series_genres
from app.services.tmdb_service import TMDBService


def normalize_keyword(kw):
    return kw.strip().replace("-", " ").replace("_", " ").title()


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

    async def generate_rows(self, profile: UserTasteProfile, content_type: str = "movie") -> list[RowDefinition]:
        """
        Generate a diverse set of 3-5 thematic rows.
        Async to allow fetching names for keywords.
        """
        rows = []

        # Extract features
        top_genres = profile.get_top_genres(limit=3)  # [(id, score), ...]
        top_keywords = profile.get_top_keywords(limit=4)  # [(id, score), ...]
        top_countries = profile.get_top_countries(limit=1)  # [(code, score)]
        top_years = profile.years.get_top_features(limit=1)  # [(decade_start, score)]

        genre_map = movie_genres if content_type == "movie" else series_genres

        # Helper to get genre name safely
        def get_gname(gid):
            return genre_map.get(gid, "Movies")

        def get_cname(code):
            adjectives = COUNTRY_ADJECTIVES.get(code, [])
            if adjectives:
                return random.choice(adjectives)
            return ""

        # Strategy 1: Combined Keyword Row (Top Priority)
        if top_keywords:
            k_id1 = top_keywords[0][0]
            kw_name1 = await self._get_keyword_name(k_id1)

            use_single_keyword_row = True
            if len(top_keywords) >= 2:
                k_id2 = top_keywords[1][0]
                kw_name2 = await self._get_keyword_name(k_id2)
                title = ""
                if kw_name1 and kw_name2:
                    title = gemini_service.generate_content(f"Keywords: {kw_name1} + {kw_name2}")

                if title:
                    rows.append(
                        RowDefinition(
                            title=title,
                            id=f"watchly.theme.k{k_id1}.k{k_id2}",
                            keywords=[k_id1, k_id2],
                        )
                    )
                    use_single_keyword_row = False

            if use_single_keyword_row and kw_name1:
                rows.append(
                    RowDefinition(
                        title=normalize_keyword(kw_name1),
                        id=f"watchly.theme.k{k_id1}",
                        keywords=[k_id1],
                    )
                )

        # Strategy 2: Keyword + Genre (Specific Niche)
        if top_genres and len(top_keywords) > 2:
            g_id = top_genres[0][0]
            # get random keywords: Just to surprise user in every refresh
            k_id = random.choice(top_keywords[2:])[0]

            if k_id:
                kw_name = await self._get_keyword_name(k_id)
                if kw_name:
                    title = gemini_service.generate_content(
                        f"Genre: {get_gname(g_id)} + Keyword: {normalize_keyword(kw_name)}"
                    )
                    if not title:
                        title = f"{get_gname(g_id)} {normalize_keyword(kw_name)}"
                        # keyword and genre can have same name sometimes, remove if so
                        title = " ".join(dict.fromkeys(title.split()))

                    rows.append(
                        RowDefinition(
                            title=title,
                            id=f"watchly.theme.g{g_id}.k{k_id}",
                            genres=[g_id],
                            keywords=[k_id],
                        )
                    )

        # Strategy 3: Genre + Country (e.g. "Bollywood Action")
        if top_countries and len(top_genres) > 0:
            g_id = top_genres[0][0] if len(top_genres) == 1 else top_genres[1][0]
            c_code = top_countries[0][0]
            c_adj = get_cname(c_code)
            if c_adj:
                title = gemini_service.generate_content(f"Genre: {get_gname(g_id)} + Country: {c_adj}")
                if not title:
                    title = f"{get_gname(g_id)} {c_adj}"
                rows.append(
                    RowDefinition(
                        title=title,
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
            # # Only do this if decade is valid and somewhat old (nostalgia factor)
            if 1970 <= decade_start <= 2010:
                decade_str = str(decade_start)[2:] + "s"  # "90s"
                title = gemini_service.generate_content(f"Genre: {get_gname(g_id)} + Era: {decade_str}")
                if not title:
                    title = f"{get_gname(g_id)} {decade_str}"
                rows.append(
                    RowDefinition(
                        title=title,
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
