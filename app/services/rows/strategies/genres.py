import random

from app.services.gemini import gemini_service
from app.services.rows.models import RowDefinition, RowStrategy
from app.services.rows.utils import normalize_keyword
from app.services.tmdb.countries import COUNTRY_ADJECTIVES
from app.services.tmdb.genre import movie_genres, series_genres


class GenreNicheStrategy(RowStrategy):
    def __init__(self, tmdb_service):
        self.tmdb_service = tmdb_service

    async def _get_keyword_name(self, keyword_id: int) -> str | None:
        try:
            data = await self.tmdb_service.make_request(f"/keyword/{keyword_id}")
            return data.get("name")
        except Exception:
            return None

    def _get_gname(self, gid, content_type):
        genre_map = movie_genres if content_type == "movie" else series_genres
        return genre_map.get(gid, "Movies")

    def _get_cname(self, code):
        adjectives = COUNTRY_ADJECTIVES.get(code, [])
        return random.choice(adjectives) if adjectives else ""

    async def generate(self, profile, content_type: str) -> list[RowDefinition]:
        rows = []
        top_genres = profile.get_top_genres(limit=3)
        top_keywords = profile.get_top_keywords(limit=4)
        top_countries = profile.get_top_countries(limit=1)

        # 1. Genre + Keyword
        if top_genres and len(top_keywords) > 2:
            row = await self._create_genre_keyword_row(top_genres, top_keywords, content_type)
            if row:
                rows.append(row)

        # 2. Genre + Country
        if top_countries and len(top_genres) > 0:
            row = await self._create_genre_country_row(top_genres, top_countries, content_type)
            if row:
                rows.append(row)

        return rows

    async def _create_genre_keyword_row(self, top_genres, top_keywords, content_type):
        g_id = top_genres[0][0]
        # Pick a random keyword from the tail to ensure variety
        candidates = top_keywords[2:]
        if not candidates:
            return None

        k_id = random.choice(candidates)[0]
        kw_name = await self._get_keyword_name(k_id)
        if not kw_name:
            return None

        g_name = self._get_gname(g_id, content_type)
        nice_kw_name = normalize_keyword(kw_name)

        title = await gemini_service.generate_content_async(f"Genre: {g_name} + Keyword: {nice_kw_name}")
        if not title:
            # Fallback title
            title = f"{nice_kw_name} {g_name}"
            title = " ".join(dict.fromkeys(title.split()))  # Dedup words

        return RowDefinition(title=title, id=f"watchly.theme.g{g_id}.k{k_id}", genres=[g_id], keywords=[k_id])

    async def _create_genre_country_row(self, top_genres, top_countries, content_type):
        # Use 2nd genre for variety if available
        g_id = top_genres[0][0] if len(top_genres) == 1 else top_genres[1][0]
        c_code = top_countries[0][0]
        c_adj = self._get_cname(c_code)

        if not c_adj:
            return None

        g_name = self._get_gname(g_id, content_type)
        title = await gemini_service.generate_content_async(f"Genre: {g_name} + Country: {c_adj}")
        if not title:
            title = f"{c_adj} {g_name}"

        return RowDefinition(title=title, id=f"watchly.theme.g{g_id}.ct{c_code}", genres=[g_id], country=c_code)
