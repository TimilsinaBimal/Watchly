from app.services.gemini import gemini_service
from app.services.rows.models import RowDefinition, RowStrategy
from app.services.tmdb.genre import movie_genres, series_genres


class LegacyStrategy(RowStrategy):
    def __init__(self, tmdb_service):
        self.tmdb_service = tmdb_service

    def _get_gname(self, gid, content_type):
        return (movie_genres if content_type == "movie" else series_genres).get(gid, "Movies")

    async def generate(self, profile, content_type: str) -> list[RowDefinition]:
        top_genres = profile.get_top_genres(limit=3)
        top_years = profile.years.get_top_features(limit=1)

        if len(top_genres) > 0 and top_years:
            row = await self._create_nostalgia_row(top_genres, top_years, content_type)
            if row:
                return [row]
        return []

    async def _create_nostalgia_row(self, top_genres, top_years, content_type):
        # Use 3rd genre for diversity if possible, else 1st
        g_id = top_genres[2][0] if len(top_genres) > 2 else top_genres[0][0]
        decade_start = top_years[0][0]

        # Strict Classic Condition: Ignore 2010s and 2020s (pre-2010 only)
        if not (1960 <= decade_start < 2010):
            return None

        decade_str = f"{str(decade_start)[2:]}s"  # "90s"
        g_name = self._get_gname(g_id, content_type)

        title = await gemini_service.generate_content_async(f"Genre: {g_name} + Era: {decade_str}")
        if not title:
            title = f"{decade_str} {g_name}"

        return RowDefinition(
            title=title,
            id=f"watchly.theme.g{g_id}.y{decade_start}",
            genres=[g_id],
            year_range=(decade_start, decade_start + 9),
        )
