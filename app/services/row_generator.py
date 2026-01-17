"""
Dynamic Row Generator Service.

Generates 3 personalized catalog rows using a tiered sampling system:
- Row 1 (The Core): User's strongest preferences (Gold tier: Top 1-3)
- Row 2 (The Blend): Mixed preferences with higher complexity (Gold+Silver: Top 1-8)
- Row 3 (The Rising Star): Emerging interests (Silver tier: Rank 4-10)
"""

import asyncio
import random
from enum import Enum
from typing import Any

from loguru import logger
from pydantic import BaseModel

from app.models.taste_profile import TasteProfile
from app.services.gemini import gemini_service
from app.services.tmdb.countries import COUNTRY_ADJECTIVES
from app.services.tmdb.genre import movie_genres, series_genres
from app.services.tmdb.service import TMDBService, get_tmdb_service

GOLD_TIER_LIMIT = 3  # Top 1-3 items
SILVER_TIER_START = 3  # Rank 4+
SILVER_TIER_END = 10  # Up to Rank 10

# Available axes for row generation
AXIS_GENRE = "genre"
AXIS_KEYWORD = "keyword"
AXIS_COUNTRY = "country"
AXIS_ERA = "era"
AXIS_RUNTIME = "runtime"
AXIS_CREATOR = "creator"


class AxisRole(str, Enum):
    ANCHOR = "anchor"  # strong signal, near-required
    FLAVOR = "flavor"  # boosts relevance, optional
    FALLBACK = "fallback"  # ranking only, never filtering


class RowAxis(BaseModel):
    name: str
    value: Any
    role: AxisRole
    weight: float = 1.0


def normalize_keyword(kw: str) -> str:
    """Normalize keyword for display."""
    return kw.strip().replace("-", " ").replace("_", " ").title()


def get_genre_name(genre_id: int, content_type: str) -> str:
    """Get genre name from ID."""
    genre_map = movie_genres if content_type == "movie" else series_genres
    return genre_map.get(genre_id, "Movies" if content_type == "movie" else "Series")


def get_country_adjective(country_code: str) -> str | None:
    """Get country adjective (e.g., 'US' -> 'American')."""
    adjectives = COUNTRY_ADJECTIVES.get(country_code, [])
    return random.choice(adjectives) if adjectives else None


def era_to_decade(era: str) -> int | None:
    """Convert era string to decade start year."""
    try:
        if era.startswith("pre-"):
            return 1960
        return int(era.replace("s", ""))
    except (ValueError, AttributeError):
        return None


def decade_to_display(decade: int) -> str:
    """Convert decade to display string (e.g., 1990 -> '90s')."""
    return f"{str(decade)[2:]}s"


def runtime_to_modifier(bucket: str) -> str | None:
    """Get display modifier for runtime bucket."""
    modifiers = {
        "short": "Short & Sweet",
        "medium": None,  # No modifier for medium
        "long": "Epic",
    }
    return modifiers.get(bucket)


def sample_from_tier(items: list[tuple[Any, float]], start: int, end: int, count: int = 1) -> list[tuple[Any, float]]:
    """Sample random items from a specific tier range."""
    tier_items = items[start:end]
    if not tier_items:
        return []
    return random.sample(tier_items, min(count, len(tier_items)))


def sample_from_gold(items: list[tuple[Any, float]], count: int = 1) -> list[tuple[Any, float]]:
    """Sample from Gold tier (Top 1-3)."""
    return sample_from_tier(items, 0, GOLD_TIER_LIMIT, count)


def sample_from_silver(items: list[tuple[Any, float]], count: int = 1) -> list[tuple[Any, float]]:
    """Sample from Silver tier (Rank 4-10)."""
    return sample_from_tier(items, SILVER_TIER_START, SILVER_TIER_END, count)


def sample_from_gold_silver(items: list[tuple[Any, float]], count: int = 1) -> list[tuple[Any, float]]:
    """Sample from combined Gold+Silver tier (Rank 1-10)."""
    return sample_from_tier(items, 0, SILVER_TIER_END, count)


def build_row_id(axes: list[RowAxis]) -> str:
    """Build a unique row ID from axes and their roles."""
    parts = ["watchly.theme"]

    role_map = {
        AxisRole.ANCHOR: "a",
        AxisRole.FLAVOR: "f",
        AxisRole.FALLBACK: "b",
    }

    # Sort axes for consistent IDs
    sorted_axes = sorted(axes, key=lambda x: (x.role, x.name, str(x.value)))

    for axis in sorted_axes:
        role_pfx = role_map.get(axis.role, "f")
        axis_pfx = {
            AXIS_GENRE: "g",
            AXIS_KEYWORD: "k",
            AXIS_COUNTRY: "ct",
            AXIS_ERA: "y",
            AXIS_RUNTIME: "r",
            AXIS_CREATOR: "cr",
        }.get(axis.name, "x")

        # Handle value formatting
        val = axis.value
        if isinstance(val, (list, tuple)):
            val = "-".join(str(v) for v in val)

        parts.append(f"{role_pfx}:{axis_pfx}{val}")

    return ".".join(parts)


class RowDefinition(BaseModel):
    """Defines a dynamic catalog row."""

    title: str
    id: str
    axes: list[RowAxis] = []
    explanation: str | None = None
    expansion_strategy: str | None = None

    @property
    def is_valid(self) -> bool:
        return len(self.axes) > 0


class RowComponents(BaseModel):
    """Internal structure for building a row."""

    axes: list[RowAxis] = []
    explanation: str | None = None

    # For title generation
    prompt_parts: list[str] = []
    fallback_parts: list[str] = []

    def build_prompt(self) -> str:
        """Build Gemini prompt from parts."""
        return " + ".join(self.prompt_parts)

    def build_fallback(self) -> str:
        """Build fallback title from parts."""
        return " ".join(self.fallback_parts)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for row building."""
        return {
            "axes": self.axes,
            "explanation": self.explanation,
        }


class ExtractedFeatures:
    """Container for all extracted profile features with keyword names resolved."""

    def __init__(
        self,
        genres: list[tuple[int, float]],
        keywords: list[tuple[int, float]],
        countries: list[tuple[str, float]],
        eras: list[tuple[str, float]],
        runtimes: list[tuple[str, float]],
        creators: list[tuple[int, float]],
        keyword_names: dict[int, str],
        content_type: str,
    ):
        self.genres = genres
        self.keywords = keywords
        self.countries = countries
        self.eras = eras
        self.runtimes = runtimes
        self.creators = creators
        self.keyword_names = keyword_names
        self.content_type = content_type

    def get_keyword_name(self, keyword_id: int) -> str | None:
        return self.keyword_names.get(keyword_id)

    def get_genre_name(self, genre_id: int) -> str:
        return get_genre_name(genre_id, self.content_type)


class RowBuilder:
    """Builds a single row by sampling from axes with specific roles."""

    def __init__(self, features: ExtractedFeatures):
        self.features = features
        self.components = RowComponents()
        self.used_axes: set[str] = set()

    def add_axis(self, name: str, value: Any, role: AxisRole, weight: float = 1.0) -> "RowBuilder":
        """Add an axis with a specific role and weight."""
        axis = RowAxis(name=name, value=value, role=role, weight=weight)
        self.components.axes.append(axis)

        # Build prompt and fallback title parts
        display_val = self._get_display_value(name, value)
        if display_val:
            prefix = ""
            if role == AxisRole.ANCHOR:
                prefix = "Anchor: "
            elif role == AxisRole.FLAVOR:
                prefix = "Flavor: "

            self.components.prompt_parts.append(f"{prefix}{name.title()}: {display_val}")

            # For fallback title, we prioritize Anchor and Flavor
            if role in (AxisRole.ANCHOR, AxisRole.FLAVOR):
                if name == AXIS_COUNTRY:
                    self.components.fallback_parts.insert(0, display_val)
                else:
                    self.components.fallback_parts.append(display_val)

        self.used_axes.add(f"{name}:{value}")
        return self

    def _get_display_value(self, name: str, value: Any) -> str | None:
        """Get human-readable value for an axis."""
        if name == AXIS_GENRE:
            return self.features.get_genre_name(value)
        if name == AXIS_KEYWORD:
            return normalize_keyword(self.features.get_keyword_name(value) or "")
        if name == AXIS_COUNTRY:
            return get_country_adjective(value)
        if name == AXIS_ERA:
            return decade_to_display(value[0]) if isinstance(value, (list, tuple)) else f"{value}s"
        if name == AXIS_RUNTIME:
            return runtime_to_modifier(value)
        return str(value)

    def build(self) -> RowComponents | None:
        """Build and return the row components if valid (has at least one anchor)."""
        has_anchor = any(a.role == AxisRole.ANCHOR for a in self.components.axes)
        if has_anchor:
            return self.components
        return None


class RowGeneratorService:
    """Generates dynamic, personalized row definitions from a User Taste Profile."""

    def __init__(self, tmdb_service: TMDBService | None = None):
        self.tmdb_service = tmdb_service or get_tmdb_service()

    async def generate_rows(self, profile: TasteProfile, content_type: str = "movie") -> list[RowDefinition]:
        """
        Generate exactly 3 personalized catalog rows: One Core, One Blend, One Rising Star.
        Total 6 rows across both content types (movie/series).

        Returns:
            List of RowDefinition
        """
        # 1. Extract all features from profile
        features = await self._extract_features(profile, content_type)

        # 2. Build exactly one of each persona with inter-row diversity
        rows_data = []
        used_genres = set()
        used_keywords = set()

        # Row 1: The Core (Strongest matches)
        core_row = self._build_core_row(features, exclude_genres=used_genres, exclude_keywords=used_keywords)
        if core_row:
            rows_data.append(core_row)
            self._update_used_axes(core_row, used_genres, used_keywords)

        # Row 2: The Blend (Mixing themes)
        blend_row = self._build_blend_row(features, exclude_genres=used_genres, exclude_keywords=used_keywords)
        if blend_row:
            rows_data.append(blend_row)
            self._update_used_axes(blend_row, used_genres, used_keywords)

        # Row 3: The Rising Star (Exploration)
        rising_row = self._build_rising_star_row(features, exclude_genres=used_genres, exclude_keywords=used_keywords)
        if rising_row:
            rows_data.append(rising_row)

        # 3. Generate titles via Gemini (parallel)
        # We limit to 3 rows total per call
        final_rows = await self._generate_titles(rows_data[:3])

        logger.info(f"Generated {len(final_rows)} dynamic rows (Core/Blend/Rising) for {content_type}")
        return final_rows

    def _update_used_axes(self, row: RowComponents, used_genres: set, used_keywords: set):
        """Track used genres and keywords to ensure row diversity."""
        for axis in row.axes:
            if axis.name == AXIS_GENRE:
                used_genres.add(axis.value)
            elif axis.name == AXIS_KEYWORD:
                used_keywords.add(axis.value)

    async def _extract_features(self, profile: TasteProfile, content_type: str) -> ExtractedFeatures:
        """Extract all features from profile and resolve keyword names."""
        # Get raw features
        genres = profile.get_top_genres(limit=5)
        keywords = profile.get_top_keywords(limit=10)
        countries = profile.get_top_countries(limit=2)
        eras = profile.get_top_eras(limit=2)
        runtimes = sorted(profile.runtime_bucket_scores.items(), key=lambda x: x[1], reverse=True)
        creators = profile.get_top_creators(limit=5)

        # Fetch keyword names in parallel
        keyword_ids = [k_id for k_id, _ in keywords]
        keyword_names_raw = await asyncio.gather(
            *[self._get_keyword_name(kid) for kid in keyword_ids],
            return_exceptions=True,
        )
        keyword_names = {
            kid: name for kid, name in zip(keyword_ids, keyword_names_raw) if name and not isinstance(name, Exception)
        }

        return ExtractedFeatures(
            genres=genres,
            keywords=keywords,
            countries=countries,
            eras=eras,
            runtimes=runtimes,
            creators=creators,
            keyword_names=keyword_names,
            content_type=content_type,
        )

    async def _get_keyword_name(self, keyword_id: int) -> str | None:
        """Fetch keyword name from TMDB."""
        try:
            data = await self.tmdb_service.get_keyword_details(keyword_id)
            return data.get("name")
        except Exception:
            return None

    def _build_core_row(
        self,
        features: ExtractedFeatures,
        exclude_genres: set[int] | None = None,
        exclude_keywords: set[int] | None = None,
    ) -> RowComponents | None:
        """
        Build 'The Core' row:
        Anchor: GENRE (Gold)
        Flavor: 1-2 KEYWORDS (Gold)
        Fallback: ERA or RUNTIME (Gold/Silver)
        """
        exclude_genres = exclude_genres or set()
        exclude_keywords = exclude_keywords or set()
        builder = RowBuilder(features)

        # 1. Anchor: Genre
        available_genres = [g for g in features.genres if g[0] not in exclude_genres]
        genres = sample_from_gold(available_genres, 1) if available_genres else sample_from_gold(features.genres, 1)
        if not genres:
            return None
        builder.add_axis(AXIS_GENRE, genres[0][0], AxisRole.ANCHOR, 1.0)

        # 2. Flavor: 1-2 Keywords
        available_keywords = [k for k in features.keywords if k[0] not in exclude_keywords]
        keywords = sample_from_gold(available_keywords, random.randint(1, 2)) if available_keywords else []
        for k_id, _ in keywords:
            builder.add_axis(AXIS_KEYWORD, k_id, AxisRole.FLAVOR, 0.7)

        # 3. Fallback: Era or Runtime
        if random.random() < 0.5 and features.eras:
            era = sample_from_gold_silver(features.eras, 1)
            decade = era_to_decade(era[0][0])
            if decade:
                builder.add_axis(AXIS_ERA, (decade, decade + 9), AxisRole.FALLBACK, 0.3)
        elif features.runtimes:
            runtime = random.choice(features.runtimes[:2])
            builder.add_axis(AXIS_RUNTIME, runtime[0], AxisRole.FALLBACK, 0.3)

        row = builder.build()
        if row:
            row.explanation = "The Core: Based on your absolute favorite genres and recurring themes."
        return row

    def _build_blend_row(
        self,
        features: ExtractedFeatures,
        exclude_genres: set[int] | None = None,
        exclude_keywords: set[int] | None = None,
    ) -> RowComponents | None:
        """
        Build 'The Blend' row:
        Anchor: GENRE (Gold)
        Flavor: COUNTRY or ERA or secondary GENRE (Gold/Silver)
        """
        exclude_genres = exclude_genres or set()
        builder = RowBuilder(features)

        # 1. Anchor: Genre
        available_genres = [g for g in features.genres if g[0] not in exclude_genres]
        genres = sample_from_gold(available_genres, 1) if available_genres else sample_from_gold(features.genres, 1)
        if not genres:
            return None
        builder.add_axis(AXIS_GENRE, genres[0][0], AxisRole.ANCHOR, 1.0)

        # 2. Flavor: Country, Era, or Secondary Genre
        flavor_type = random.choice([AXIS_COUNTRY, AXIS_ERA, AXIS_GENRE])

        if flavor_type == AXIS_COUNTRY and features.countries:
            country = sample_from_gold_silver(features.countries, 1)
            builder.add_axis(AXIS_COUNTRY, country[0][0], AxisRole.FLAVOR, 0.7)
        elif flavor_type == AXIS_ERA and features.eras:
            era = sample_from_gold_silver(features.eras, 1)
            decade = era_to_decade(era[0][0])
            if decade:
                builder.add_axis(AXIS_ERA, (decade, decade + 9), AxisRole.FLAVOR, 0.7)
        elif flavor_type == AXIS_GENRE:
            other_genres = [g for g in features.genres if g[0] != genres[0][0]]
            if other_genres:
                sec_genre = sample_from_gold_silver(other_genres, 1)
                builder.add_axis(AXIS_GENRE, sec_genre[0][0], AxisRole.FLAVOR, 0.7)

        row = builder.build()
        if row:
            row.explanation = "The Blend: Mixing your top genres with preferred eras or international flavor."
        return row

    def _build_rising_star_row(
        self,
        features: ExtractedFeatures,
        exclude_genres: set[int] | None = None,
        exclude_keywords: set[int] | None = None,
    ) -> RowComponents | None:
        """
        Build 'The Rising Star' row:
        Anchor: recent KEYWORD or ERA (Silver)
        Flavor: GENRE (Silver)
        Fallback: COUNTRY (Gold/Silver)
        """
        exclude_genres = exclude_genres or set()
        exclude_keywords = exclude_keywords or set()
        builder = RowBuilder(features)

        # 1. Anchor: Recent Keyword or Era (Sampling from Silver to promote exploration)
        anchor_type = random.choice([AXIS_KEYWORD, AXIS_ERA])

        if anchor_type == AXIS_KEYWORD:
            available_keywords = [k for k in features.keywords if k[0] not in exclude_keywords]
            keywords = sample_from_silver(available_keywords, 1) if available_keywords else []
            if keywords:
                builder.add_axis(AXIS_KEYWORD, keywords[0][0], AxisRole.ANCHOR, 1.0)
        elif anchor_type == AXIS_ERA:
            eras = sample_from_silver(features.eras, 1)
            if eras:
                decade = era_to_decade(eras[0][0])
                if decade:
                    builder.add_axis(AXIS_ERA, (decade, decade + 9), AxisRole.ANCHOR, 1.0)

        # If we couldn't add an anchor, this row fails
        if not builder.components.axes:
            return None

        # 2. Flavor: Genre (Silver)
        available_genres = [g for g in features.genres if g[0] not in exclude_genres]
        genres = sample_from_silver(available_genres, 1) if available_genres else []
        if genres:
            builder.add_axis(AXIS_GENRE, genres[0][0], AxisRole.FLAVOR, 0.7)

        # 3. Fallback: Country
        if features.countries:
            country = sample_from_gold_silver(features.countries, 1)
            builder.add_axis(AXIS_COUNTRY, country[0][0], AxisRole.FALLBACK, 0.3)

        row = builder.build()
        if row:
            row.explanation = "The Rising Star: Exploring emerging interests and newer themes in your history."
        return row

    def _build_signature_rows(self, features: ExtractedFeatures) -> list[RowComponents]:
        """Generate dynamic signature recipes from user history."""
        signature_rows = []

        # 1. Top genre × dominant keyword
        if features.genres and features.keywords:
            builder = RowBuilder(features)
            builder.add_axis(AXIS_GENRE, features.genres[0][0], AxisRole.ANCHOR, 1.0)
            builder.add_axis(AXIS_KEYWORD, features.keywords[0][0], AxisRole.FLAVOR, 0.7)
            row = builder.build()
            if row:
                row.explanation = "Signature: Your #1 genre paired with your most frequent theme."
                signature_rows.append(row)

        # 2. Top genre × preferred runtime
        if features.genres and features.runtimes:
            builder = RowBuilder(features)
            builder.add_axis(AXIS_GENRE, features.genres[0][0], AxisRole.ANCHOR, 1.0)
            builder.add_axis(AXIS_RUNTIME, features.runtimes[0][0], AxisRole.FLAVOR, 0.7)
            row = builder.build()
            if row:
                row.explanation = "Signature: Favorite genre fit for your preferred watch duration."
                signature_rows.append(row)

        # 3. Recent watch era × genre
        if features.eras and features.genres:
            builder = RowBuilder(features)
            era = features.eras[0][0]
            decade = era_to_decade(era)
            if decade:
                builder.add_axis(AXIS_ERA, (decade, decade + 9), AxisRole.ANCHOR, 1.0)
                builder.add_axis(AXIS_GENRE, features.genres[0][0], AxisRole.FLAVOR, 0.7)
                row = builder.build()
                if row:
                    row.explanation = "Signature: Exploring your favorite genre within your most watched era."
                    signature_rows.append(row)

        return signature_rows

    async def _generate_titles(self, rows_data: list[RowComponents]) -> list[RowDefinition]:
        """Generate titles for all rows via Gemini."""
        if not rows_data:
            return []

        # Build prompts and fire Gemini requests
        prompts = [row.build_prompt() for row in rows_data]
        gemini_tasks = [gemini_service.generate_content_async(p) for p in prompts]
        results = await asyncio.gather(*gemini_tasks, return_exceptions=True)

        final_rows = []
        for i, row in enumerate(rows_data):
            result = results[i]

            # Determine title
            if isinstance(result, Exception):
                logger.warning(f"Gemini failed for row {i}: {result}")
                title = row.build_fallback()
            elif result:
                title = result.strip()
            else:
                title = row.build_fallback()

            # Build the row ID
            row_id = build_row_id(row.axes)

            final_rows.append(
                RowDefinition(
                    title=title,
                    id=row_id,
                    **row.to_dict(),
                )
            )

        return final_rows
