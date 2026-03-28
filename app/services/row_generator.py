"""
Dynamic Row Generator Service.

Generates 3 personalized catalog rows from a user's taste profile:
- Row 1 (Core): Strongest preferences
- Row 2 (Blend): Mixed preferences with variety
- Row 3 (Rising Star): Emerging/exploratory interests
"""

import asyncio
import random
from typing import Any

from loguru import logger
from pydantic import BaseModel, Field

from app.models.profile import TasteProfile
from app.services.gemini import gemini_service
from app.services.tmdb.countries import COUNTRY_ADJECTIVES
from app.services.tmdb.genre import movie_genres, series_genres
from app.services.tmdb.service import TMDBService, get_tmdb_service

GOLD_END = 3
SILVER_START = 3
SILVER_END = 10

ROLE_ANCHOR = "a"
ROLE_FLAVOR = "f"
ROLE_FALLBACK = "b"

AXIS_GENRE = "g"
AXIS_KEYWORD = "k"
AXIS_COUNTRY = "ct"
AXIS_RUNTIME = "r"
AXIS_CREATOR = "cr"


class RowDefinition(BaseModel):
    """A dynamic catalog row with an ID (encodes TMDB params) and a display title."""

    title: str
    id: str


class LLMRowTheme(BaseModel):
    """Schema for Gemini structured output — a single themed catalog row."""

    title: str = Field(description="Creative, short title for the collection (2-5 words)")
    genres: list[int] = Field(description="List of valid TMDB genre IDs")
    keywords: list[str] = Field(default_factory=list, description="Specific TMDB keyword names")
    country: str | None = Field(default=None, description="ISO 3166-1 country code or null")


# --- ID building (format must match theme_based.py parser) ---


def build_row_id(axes: list[tuple[str, str, Any]]) -> str:
    """Build row ID from axes. Each axis is (role, axis_type, value).

    Example output: watchly.theme.a:g28.f:k1234.b:rshort
    """
    parts = ["watchly.theme"]
    sorted_axes = sorted(axes, key=lambda x: (x[0], x[1], str(x[2])))
    for role, axis_type, value in sorted_axes:
        if isinstance(value, (list, tuple)):
            value = "-".join(str(v) for v in value)
        parts.append(f"{role}:{axis_type}{value}")
    return ".".join(parts)


# --- Display helpers ---


def _genre_name(genre_id: int, content_type: str) -> str:
    genre_map = movie_genres if content_type == "movie" else series_genres
    return genre_map.get(genre_id, "Movies" if content_type == "movie" else "Series")


def _country_adjective(code: str) -> str | None:
    adjs = COUNTRY_ADJECTIVES.get(code, [])
    return random.choice(adjs) if adjs else None


def _keyword_display(name: str) -> str:
    return name.strip().replace("-", " ").replace("_", " ").title()


def _runtime_modifier(bucket: str) -> str | None:
    return {"short": "Short & Sweet", "long": "Epic"}.get(bucket)


def _pick(items: list, start: int, end: int, exclude: set | None = None) -> Any | None:
    """Pick a random item from items[start:end], excluding IDs in `exclude`."""
    pool = items[start:end]
    if exclude:
        pool = [x for x in pool if x[0] not in exclude]
    if not pool:
        pool = items[start:end]
    return random.choice(pool) if pool else None


class RowGeneratorService:
    """Generates dynamic, personalized row definitions from a taste profile."""

    def __init__(self, tmdb_service: TMDBService | None = None):
        self.tmdb_service = tmdb_service or get_tmdb_service()

    async def generate_rows(
        self,
        profile: TasteProfile,
        content_type: str = "movie",
        api_key: str | None = None,
    ) -> list[RowDefinition]:
        """Generate up to 3 personalized catalog rows."""
        genres = profile.get_top_genres(limit=5)
        keywords = profile.get_top_keywords(limit=10)
        countries = profile.get_top_countries(limit=2)
        runtimes = sorted(profile.runtime_bucket_scores.items(), key=lambda x: x[1], reverse=True)

        keyword_names = await self._resolve_keyword_names([kid for kid, _ in keywords])

        if api_key:
            try:
                llm_rows = await self._generate_with_llm(
                    profile, genres, keywords, keyword_names, content_type, api_key
                )
                if llm_rows:
                    logger.info(f"Generated {len(llm_rows)} LLM-driven rows for {content_type}")
                    return llm_rows
            except Exception as e:
                logger.warning(f"LLM row generation failed, using fallback: {e}")

        rows = self._build_rows_fallback(genres, keywords, countries, runtimes, keyword_names, content_type)
        titled = await self._generate_titles(rows)
        logger.info(f"Generated {len(titled)} rows (fallback) for {content_type}")
        return titled

    # --- Fallback row building (non-LLM) ---

    def _build_rows_fallback(
        self,
        genres: list[tuple[int, float]],
        keywords: list[tuple[int, float]],
        countries: list[tuple[str, float]],
        runtimes: list[tuple[str, float]],
        keyword_names: dict[int, str],
        content_type: str,
    ) -> list[tuple[list[tuple[str, str, Any]], str]]:
        """Build up to 3 rows as (axes, fallback_title) tuples."""
        rows = []
        used_genres: set[int] = set()
        used_keywords: set[int] = set()

        # Row 1: Core — top genre + top keywords
        r1 = self._build_core(genres, keywords, runtimes, keyword_names, content_type, used_genres, used_keywords)
        if r1:
            rows.append(r1)

        # Row 2: Blend — genre + country or secondary genre
        r2 = self._build_blend(genres, countries, content_type, used_genres)
        if r2:
            rows.append(r2)

        # Row 3: Rising Star — emerging keyword + secondary genre + country
        r3 = self._build_rising(genres, keywords, countries, keyword_names, content_type, used_genres, used_keywords)
        if r3:
            rows.append(r3)

        return rows[:3]

    def _build_core(self, genres, keywords, runtimes, keyword_names, content_type, used_genres, used_keywords):
        axes = []
        title_parts = []

        g = _pick(genres, 0, GOLD_END, used_genres)
        if not g:
            return None
        axes.append((ROLE_ANCHOR, AXIS_GENRE, g[0]))
        title_parts.append(_genre_name(g[0], content_type))
        used_genres.add(g[0])

        for _ in range(random.randint(1, 2)):
            k = _pick(keywords, 0, GOLD_END, used_keywords)
            if k and k[0] in keyword_names:
                axes.append((ROLE_FLAVOR, AXIS_KEYWORD, k[0]))
                title_parts.append(_keyword_display(keyword_names[k[0]]))
                used_keywords.add(k[0])

        if runtimes:
            rt = random.choice(runtimes[:2])
            axes.append((ROLE_FALLBACK, AXIS_RUNTIME, rt[0]))
            mod = _runtime_modifier(rt[0])
            if mod:
                title_parts.insert(0, mod)

        return (axes, " ".join(title_parts))

    def _build_blend(self, genres, countries, content_type, used_genres):
        axes = []
        title_parts = []

        g = _pick(genres, 0, GOLD_END, used_genres)
        if not g:
            return None
        axes.append((ROLE_ANCHOR, AXIS_GENRE, g[0]))
        title_parts.append(_genre_name(g[0], content_type))
        used_genres.add(g[0])

        use_country = random.choice([True, False])
        if use_country and countries:
            c = _pick(countries, 0, SILVER_END)
            if c:
                axes.append((ROLE_FLAVOR, AXIS_COUNTRY, c[0]))
                adj = _country_adjective(c[0])
                if adj:
                    title_parts.insert(0, adj)
        else:
            other = [gx for gx in genres if gx[0] != g[0]]
            sg = _pick(other, 0, SILVER_END) if other else None
            if sg:
                axes.append((ROLE_FLAVOR, AXIS_GENRE, sg[0]))
                title_parts.append(_genre_name(sg[0], content_type))

        return (axes, " ".join(title_parts))

    def _build_rising(self, genres, keywords, countries, keyword_names, content_type, used_genres, used_keywords):
        axes = []
        title_parts = []

        k = _pick(keywords, SILVER_START, SILVER_END, used_keywords)
        if not k or k[0] not in keyword_names:
            return None
        axes.append((ROLE_ANCHOR, AXIS_KEYWORD, k[0]))
        title_parts.append(_keyword_display(keyword_names[k[0]]))
        used_keywords.add(k[0])

        g = _pick(genres, SILVER_START, SILVER_END, used_genres)
        if g:
            axes.append((ROLE_FLAVOR, AXIS_GENRE, g[0]))
            title_parts.append(_genre_name(g[0], content_type))

        if countries:
            c = _pick(countries, 0, SILVER_END)
            if c:
                axes.append((ROLE_FALLBACK, AXIS_COUNTRY, c[0]))

        return (axes, " ".join(title_parts))

    # --- Title generation via Gemini ---

    async def _generate_titles(self, rows: list[tuple[list[tuple[str, str, Any]], str]]) -> list[RowDefinition]:
        if not rows:
            return []

        prompts = [fallback for _, fallback in rows]
        results = await asyncio.gather(
            *[gemini_service.generate_content_async(p) for p in prompts],
            return_exceptions=True,
        )

        final = []
        for i, (axes, fallback) in enumerate(rows):
            result = results[i]
            title = result.strip() if isinstance(result, str) else fallback
            final.append(RowDefinition(title=title, id=build_row_id(axes)))
        return final

    # --- LLM-based generation ---

    async def _generate_with_llm(
        self,
        profile: TasteProfile,
        genres: list[tuple[int, float]],
        keywords: list[tuple[int, float]],
        keyword_names: dict[int, str],
        content_type: str,
        api_key: str,
    ) -> list[RowDefinition] | None:
        summary = profile.interest_summary or "No summary available."
        genre_map = movie_genres if content_type == "movie" else series_genres
        valid_genres = ", ".join(f"{name} (ID: {gid})" for gid, name in genre_map.items())

        profile_keywords = [name for kid, _ in keywords[:12] if (name := keyword_names.get(kid))]
        kw_list = f"Themes they already like: {', '.join(profile_keywords)}. " if profile_keywords else ""
        keyword_hint = kw_list + "You can also suggest new themes for discovery."

        prompt = (
            "Using the user's interest summary below, generate exactly 3 streaming "
            f"collections for {content_type}. "
            "Use genres (required), keywords, and country when relevant.\n\n"
            f"Interest Summary:\n{summary}\n\n"
            "Generate 3 rows:\n"
            "1. THE CORE — strongest match to their taste\n"
            "2. MIXED PREFERENCES — blend with variety\n"
            "3. RISING STAR — discovery, adjacent to their taste\n\n"
            f"Genres: use ONLY these TMDB Genre IDs: {valid_genres}\n"
            f"Keywords: {keyword_hint}\n"
            "Country: ISO 3166-1 code or null.\n"
            "Each row: title (2-5 words), genres (list of IDs), "
            "keywords (list of strings), country (string or null).\n"
            "Output a JSON array of 3 objects."
        )

        data = await gemini_service.generate_structured_async(
            prompt=prompt,
            response_schema=list[LLMRowTheme],
            system_instruction=(
                "You are a creative film curator. Design 3 catalog rows from the user's interest summary. "
                "Row 1: strong match. Row 2: blend + variety. Row 3: discovery. "
                "Use genres, keywords, and country. Output valid JSON only."
            ),
            api_key=api_key,
        )

        if not data or not isinstance(data, list):
            return None

        profile_kw_map = {name.lower(): kid for kid, name in keyword_names.items()}
        final = []

        for item in data:
            if isinstance(item, dict):
                title, genre_ids, kw_names, country = (
                    item.get("title", "Recommended"),
                    item.get("genres", []),
                    item.get("keywords", []),
                    item.get("country"),
                )
            else:
                title, genre_ids, kw_names, country = item.title, item.genres, item.keywords, item.country

            axes: list[tuple[str, str, Any]] = []
            for gid in genre_ids:
                if int(gid) in genre_map:
                    axes.append((ROLE_ANCHOR, AXIS_GENRE, int(gid)))

            for kw_name in kw_names:
                kid = await self._resolve_keyword_to_id(kw_name, profile_kw_map)
                if kid is not None:
                    axes.append((ROLE_FLAVOR, AXIS_KEYWORD, kid))

            if country:
                axes.append((ROLE_FLAVOR, AXIS_COUNTRY, country))

            if axes:
                final.append(RowDefinition(title=title, id=build_row_id(axes)))

        return final if final else None

    # --- Helpers ---

    async def _resolve_keyword_names(self, keyword_ids: list[int]) -> dict[int, str]:
        results = await asyncio.gather(
            *[self._get_keyword_name(kid) for kid in keyword_ids],
            return_exceptions=True,
        )
        return {kid: name for kid, name in zip(keyword_ids, results) if isinstance(name, str) and name}

    async def _get_keyword_name(self, keyword_id: int) -> str | None:
        try:
            data = await self.tmdb_service.get_keyword_details(keyword_id)
            return data.get("name")
        except Exception:
            return None

    async def _resolve_keyword_to_id(self, kw_name: str, profile_kw_map: dict[str, int]) -> int | None:
        kw_lower = str(kw_name).strip().lower()
        if not kw_lower:
            return None
        if kw_lower in profile_kw_map:
            return profile_kw_map[kw_lower]
        try:
            data = await self.tmdb_service.search_keywords(kw_lower)
            results = data.get("results") or []
            if results:
                first = results[0]
                kid = first.get("id") if isinstance(first, dict) else getattr(first, "id", None)
                if kid is not None:
                    return int(kid)
        except Exception:
            pass
        return None
