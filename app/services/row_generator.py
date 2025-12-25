import asyncio
import random

from loguru import logger
from pydantic import BaseModel

from app.models.taste_profile import TasteProfile
from app.services.gemini import gemini_service
from app.services.tmdb.countries import COUNTRY_ADJECTIVES
from app.services.tmdb.genre import movie_genres, series_genres
from app.services.tmdb.service import TMDBService, get_tmdb_service


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
        self.tmdb_service = tmdb_service or get_tmdb_service()

    async def generate_rows(self, profile: TasteProfile, content_type: str = "movie") -> list[RowDefinition]:
        """
        Generate a diverse set of 3-5 thematic rows in parallel.
        """
        # 1. Extract features
        top_genres = profile.get_top_genres(limit=3)
        top_keywords = profile.get_top_keywords(limit=6)
        top_countries = profile.get_top_countries(limit=1)
        # Convert era to decade for year extraction
        top_eras = profile.get_top_eras(limit=1)
        top_years = []
        if top_eras:
            era = top_eras[0][0]
            try:
                if era.startswith("pre-"):
                    decade = 1960
                else:
                    decade = int(era.replace("s", ""))
                top_years = [(decade, top_eras[0][1])]
            except (ValueError, AttributeError):
                pass

        # 2. Fetch all keyword names in parallel
        kw_ids = [k_id for k_id, _ in top_keywords]
        kw_names = await asyncio.gather(*[self._get_keyword_name(kid) for kid in kw_ids], return_exceptions=True)
        keyword_map = {kid: name for kid, name in zip(kw_ids, kw_names) if name and not isinstance(name, Exception)}

        genre_map = movie_genres if content_type == "movie" else series_genres

        def get_gname(gid):
            return genre_map.get(gid, "Movies")

        def get_cname(code):
            adjectives = COUNTRY_ADJECTIVES.get(code, [])
            return random.choice(adjectives) if adjectives else ""

        # 3. Define Strategy Candidates & Gemini Tasks
        gemini_tasks = []
        rows_to_build = []  # List of (builder_func, prompt_index_or_none)

        # Strategy 1: Keywords
        if top_keywords:
            k_id1 = top_keywords[0][0]
            kw_name1 = keyword_map.get(k_id1)

            if len(top_keywords) >= 2:
                k_id2 = top_keywords[1][0]
                kw_name2 = keyword_map.get(k_id2)
                if kw_name1 and kw_name2:
                    prompt = f"Keywords: {kw_name1} + {kw_name2}"
                    gemini_tasks.append(gemini_service.generate_content_async(prompt))
                    rows_to_build.append(
                        {
                            "id": f"watchly.theme.k{k_id1}.k{k_id2}",
                            "keywords": [k_id1, k_id2],
                            "prompt_idx": len(gemini_tasks) - 1,
                            "fallback": None,  # Will use Strategy 1.1 if this fails
                        }
                    )
                elif kw_name1:
                    rows_to_build.append(
                        {"id": f"watchly.theme.k{k_id1}", "keywords": [k_id1], "title": normalize_keyword(kw_name1)}
                    )
            elif kw_name1:
                rows_to_build.append(
                    {"id": f"watchly.theme.k{k_id1}", "keywords": [k_id1], "title": normalize_keyword(kw_name1)}
                )

        # Strategy 2: Genre + Keyword
        if top_genres and len(top_keywords) > 2:
            g_id = top_genres[0][0]
            k_id = random.choice(top_keywords[2:])[0]
            kw_name = keyword_map.get(k_id)
            if kw_name:
                prompt = f"Genre: {get_gname(g_id)} + Keyword: {normalize_keyword(kw_name)}"
                gemini_tasks.append(gemini_service.generate_content_async(prompt))
                rows_to_build.append(
                    {
                        "id": f"watchly.theme.g{g_id}.k{k_id}",
                        "genres": [g_id],
                        "keywords": [k_id],
                        "prompt_idx": len(gemini_tasks) - 1,
                        "fallback": f"{normalize_keyword(kw_name)} {get_gname(g_id)}",
                    }
                )

        # Strategy 3: Genre + Country
        if top_countries and len(top_genres) > 0:
            g_id = top_genres[0][0] if len(top_genres) == 1 else top_genres[1][0]
            c_code = top_countries[0][0]
            c_adj = get_cname(c_code)
            if c_adj:
                prompt = f"Genre: {get_gname(g_id)} + Country: {c_adj}"
                gemini_tasks.append(gemini_service.generate_content_async(prompt))
                rows_to_build.append(
                    {
                        "id": f"watchly.theme.g{g_id}.ct{c_code}",
                        "genres": [g_id],
                        "country": c_code,
                        "prompt_idx": len(gemini_tasks) - 1,
                        "fallback": f"{c_adj} {get_gname(g_id)}",
                    }
                )

        # Strategy 4: Genre + Era
        if len(top_genres) > 0 and top_years:
            g_id = top_genres[2][0] if len(top_genres) > 2 else top_genres[0][0]
            decade_start = top_years[0][0]
            if 1970 <= decade_start <= 2010:
                decade_str = f"{str(decade_start)[2:]}s"
                prompt = f"Genre: {get_gname(g_id)} + Era: {decade_str}"
                gemini_tasks.append(gemini_service.generate_content_async(prompt))
                rows_to_build.append(
                    {
                        "id": f"watchly.theme.g{g_id}.y{decade_start}",
                        "genres": [g_id],
                        "year_range": (decade_start, decade_start + 9),
                        "prompt_idx": len(gemini_tasks) - 1,
                        "fallback": f"{decade_str} {get_gname(g_id)}",
                    }
                )

        # 4. Execute all Gemini tasks in parallel
        gemini_results = await asyncio.gather(*gemini_tasks, return_exceptions=True)

        # 5. Build Final Rows
        final_rows = []
        # Support for Strategy 1 fallback (single keyword if dual fails)
        strategy1_success = False

        for r in rows_to_build:
            title = r.get("title")
            idx = r.get("prompt_idx")

            if title is None and idx is not None:
                res = gemini_results[idx]
                if not isinstance(res, Exception) and res:
                    title = res
                    if "k" in r["id"] and "." in r["id"]:  # Strategy 1 (dual)
                        strategy1_success = True
                else:
                    if isinstance(res, Exception):
                        logger.warning(f"Gemini failed for strategy {r['id']}: {res}")
                    title = r.get("fallback")

            if title:
                # Cleanup title
                title = " ".join(dict.fromkeys(title.split())) if r.get("genres") and r.get("keywords") else title
                final_rows.append(
                    RowDefinition(
                        title=title,
                        id=r["id"],
                        genres=r.get("genres", []),
                        keywords=r.get("keywords", []),
                        country=r.get("country"),
                        year_range=r.get("year_range"),
                    )
                )

        # Handle Strategy 1 fallback if dual keyword failed to generate or was never added
        if top_keywords and not strategy1_success:
            k1 = top_keywords[0][0]
            name1 = keyword_map.get(k1)
            # Only add if it's not already in final_rows (it might be there if dual wasn't possible)
            if name1 and not any(row.id == f"watchly.theme.k{k1}" for row in final_rows):
                final_rows.insert(
                    0, RowDefinition(title=normalize_keyword(name1), id=f"watchly.theme.k{k1}", keywords=[k1])
                )

        return final_rows

    async def _get_keyword_name(self, keyword_id: int) -> str | None:
        try:
            data = await self.tmdb_service.get_keyword_details(keyword_id)
            return data.get("name")
        except Exception as e:
            logger.exception(f"Failed to fetch keyword name: {e}", exc_info=True)
            return None
