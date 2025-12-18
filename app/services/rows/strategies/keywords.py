from app.services.gemini import gemini_service
from app.services.rows.models import RowDefinition, RowStrategy
from app.services.rows.utils import normalize_keyword


class KeywordStrategy(RowStrategy):
    def __init__(self, tmdb_service):
        self.tmdb_service = tmdb_service

    async def _get_keyword_name(self, keyword_id: int) -> str | None:
        try:
            data = await self.tmdb_service.make_request(f"/keyword/{keyword_id}")
            return data.get("name")
        except Exception:
            return None

    async def generate(self, profile, content_type: str) -> list[RowDefinition]:
        top_keywords = profile.get_top_keywords(limit=4)
        if not top_keywords:
            return []

        rows = []
        # Strategy A: Mixed Keywords (e.g. "Space" + "War")
        if len(top_keywords) >= 2:
            row = await self._create_mixed_row(top_keywords)
            if row:
                rows.append(row)

        # Strategy B: Single Top Keyword (if mixture failed or we want variety)
        # Note: Original logic skipped single if mixed succeeded.
        # Let's keep original logic: only fallback if mixed wasn't created
        if not rows:
            row = await self._create_single_row(top_keywords[0][0])
            if row:
                rows.append(row)

        return rows

    async def _create_mixed_row(self, keywords):
        k1, k2 = keywords[0][0], keywords[1][0]
        n1 = await self._get_keyword_name(k1)
        n2 = await self._get_keyword_name(k2)

        if n1 and n2:
            title = await gemini_service.generate_content_async(f"Keywords: {n1} + {n2}")
            if title:
                return RowDefinition(title=title, id=f"watchly.theme.k{k1}.k{k2}", keywords=[k1, k2])
        return None

    async def _create_single_row(self, kid):
        name = await self._get_keyword_name(kid)
        if name:
            return RowDefinition(title=normalize_keyword(name), id=f"watchly.theme.k{kid}", keywords=[kid])
        return None
