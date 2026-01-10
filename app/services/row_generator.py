"""
Dynamic Row Generator Service.

Generates 3 personalized catalog rows using a tiered sampling system:
- Row 1 (The Core): User's strongest preferences (Gold tier: Top 1-3)
- Row 2 (The Blend): Mixed preferences with higher complexity (Gold+Silver: Top 1-8)
- Row 3 (The Rising Star): Emerging interests (Silver tier: Rank 4-10)
"""

import asyncio
import random
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
        "short": "Quick",
        "medium": None,  # No modifier for medium
        "long": "Bingeworthy",
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


def build_row_id(components: dict[str, Any]) -> str:
    """Build a unique row ID from components."""
    parts = ["watchly.theme"]

    if components.get("genres"):
        for g in components["genres"]:
            parts.append(f"g{g}")
    if components.get("keywords"):
        for k in components["keywords"]:
            parts.append(f"k{k}")
    if components.get("country"):
        parts.append(f"ct{components['country']}")
    if components.get("year_range"):
        parts.append(f"y{components['year_range'][0]}")
    if components.get("runtime"):
        parts.append(f"r{components['runtime']}")
    if components.get("creator"):
        parts.append(f"cr{components['creator']}")

    return ".".join(parts)


class RowDefinition(BaseModel):
    """Defines a dynamic catalog row."""

    title: str
    id: str
    genres: list[int] = []
    keywords: list[int] = []
    country: str | None = None
    year_range: tuple[int, int] | None = None
    runtime: str | None = None
    creator: int | None = None

    @property
    def is_valid(self) -> bool:
        return bool(self.genres or self.keywords or self.country or self.year_range or self.runtime or self.creator)


class RowComponents(BaseModel):
    """Internal structure for building a row."""

    genres: list[int] = []
    keywords: list[int] = []
    country: str | None = None
    year_range: tuple[int, int] | None = None
    runtime: str | None = None
    creator: int | None = None

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
            "genres": self.genres,
            "keywords": self.keywords,
            "country": self.country,
            "year_range": self.year_range,
            "runtime": self.runtime,
            "creator": self.creator,
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
    """Builds a single row by sampling from axes."""

    def __init__(self, features: ExtractedFeatures):
        self.features = features
        self.components = RowComponents()
        self.used_genres: set[int] = set()
        self.used_keywords: set[int] = set()

    def add_genre(self, genre_id: int) -> "RowBuilder":
        """Add a genre to the row."""
        self.components.genres.append(genre_id)
        name = self.features.get_genre_name(genre_id)
        self.components.prompt_parts.append(f"Genre: {name}")
        self.components.fallback_parts.append(name)
        self.used_genres.add(genre_id)
        return self

    def add_keyword(self, keyword_id: int) -> "RowBuilder":
        """Add a keyword to the row."""
        name = self.features.get_keyword_name(keyword_id)
        if name:
            self.components.keywords.append(keyword_id)
            self.components.prompt_parts.append(f"Keyword: {normalize_keyword(name)}")
            self.components.fallback_parts.append(normalize_keyword(name))
            self.used_keywords.add(keyword_id)
        return self

    def add_country(self, country_code: str) -> "RowBuilder":
        """Add a country to the row."""
        adj = get_country_adjective(country_code)
        if adj:
            self.components.country = country_code
            self.components.prompt_parts.append(f"Country: {adj}")
            self.components.fallback_parts.insert(0, adj)  # Country goes first
        return self

    def add_era(self, decade: int) -> "RowBuilder":
        """Add an era to the row."""
        if 1960 <= decade <= 2020:
            self.components.year_range = (decade, decade + 9)
            display = decade_to_display(decade)
            self.components.prompt_parts.append(f"Era: {display}")
            self.components.fallback_parts.insert(0, display)
        return self

    def add_runtime(self, bucket: str) -> "RowBuilder":
        """Add a runtime bucket to the row."""
        modifier = runtime_to_modifier(bucket)
        if modifier:
            self.components.runtime = bucket
            self.components.prompt_parts.append(f"Runtime: {modifier}")
            self.components.fallback_parts.insert(0, modifier)
        return self

    def build(self) -> RowComponents | None:
        """Build and return the row components if valid."""
        if self.components.prompt_parts:
            return self.components
        return None


def get_core_recipes() -> list[list[str]]:
    """Get recipes for 'The Core' row (2-3 axes from Gold tier)."""
    return [
        [AXIS_GENRE, AXIS_KEYWORD, AXIS_RUNTIME],
        [AXIS_GENRE, AXIS_KEYWORD, AXIS_KEYWORD],
        [AXIS_KEYWORD, AXIS_KEYWORD, AXIS_RUNTIME],
        [AXIS_GENRE, AXIS_KEYWORD],
        [AXIS_KEYWORD, AXIS_KEYWORD],
    ]


def get_blend_recipes() -> list[list[str]]:
    """Get recipes for 'The Blend' row (3-4 axes from Gold+Silver)."""
    return [
        [AXIS_GENRE, AXIS_KEYWORD, AXIS_ERA],
        [AXIS_GENRE, AXIS_KEYWORD, AXIS_COUNTRY],
        [AXIS_GENRE, AXIS_COUNTRY, AXIS_RUNTIME],
        [AXIS_KEYWORD, AXIS_COUNTRY, AXIS_ERA],
        [AXIS_GENRE, AXIS_ERA, AXIS_RUNTIME],
    ]


def get_rising_star_recipes() -> list[list[str]]:
    """Get recipes for 'The Rising Star' row (2 axes from Silver tier)."""
    return [
        [AXIS_KEYWORD, AXIS_COUNTRY],
        [AXIS_GENRE, AXIS_KEYWORD],
        [AXIS_KEYWORD, AXIS_ERA],
        [AXIS_GENRE, AXIS_ERA],
        [AXIS_KEYWORD, AXIS_RUNTIME],
    ]


class RowGeneratorService:
    """Generates dynamic, personalized row definitions from a User Taste Profile."""

    def __init__(self, tmdb_service: TMDBService | None = None):
        self.tmdb_service = tmdb_service or get_tmdb_service()

    async def generate_rows(self, profile: TasteProfile, content_type: str = "movie") -> list[RowDefinition]:
        """
        Generate 3 dynamic rows using the tiered persona system.

        Returns:
            List of RowDefinition (up to 3 rows)
        """
        # 1. Extract all features from profile
        features = await self._extract_features(profile, content_type)

        # 2. Build rows for each persona
        rows_data = []

        # Row 1: The Core (Gold tier sampling)
        core_row = self._build_core_row(features)
        if core_row:
            rows_data.append(core_row)

        # Row 2: The Blend (Gold+Silver tier sampling)
        blend_row = self._build_blend_row(features, exclude_keywords=core_row.keywords if core_row else [])
        if blend_row:
            rows_data.append(blend_row)

        # Row 3: The Rising Star (Silver tier sampling)
        rising_row = self._build_rising_star_row(
            features,
            exclude_keywords=(core_row.keywords if core_row else []) + (blend_row.keywords if blend_row else []),
        )
        if rising_row:
            rows_data.append(rising_row)

        # 3. Generate titles via Gemini (parallel)
        final_rows = await self._generate_titles(rows_data)

        logger.info(f"Generated {len(final_rows)} dynamic rows for {content_type}")
        return final_rows

    async def _extract_features(self, profile: TasteProfile, content_type: str) -> ExtractedFeatures:
        """Extract all features from profile and resolve keyword names."""
        # Get raw features
        genres = profile.get_top_genres(limit=10)
        keywords = profile.get_top_keywords(limit=15)
        countries = profile.get_top_countries(limit=5)
        eras = profile.get_top_eras(limit=5)
        runtimes = sorted(profile.runtime_bucket_scores.items(), key=lambda x: x[1], reverse=True)
        creators = profile.get_top_creators(limit=10)

        # Fetch keyword names in parallel
        keyword_ids = [k_id for k_id, _ in keywords]
        keyword_names_raw = await asyncio.gather(
            *[self._get_keyword_name(kid) for kid in keyword_ids], return_exceptions=True
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

    def _build_core_row(self, features: ExtractedFeatures) -> RowComponents | None:
        """Build 'The Core' row from Gold tier (Top 1-3)."""
        recipes = get_core_recipes()
        random.shuffle(recipes)

        for recipe in recipes:
            builder = RowBuilder(features)
            if self._apply_recipe(builder, recipe, features, tier="gold"):
                return builder.build()

        return None

    def _build_blend_row(
        self, features: ExtractedFeatures, exclude_keywords: list[int] | None = None
    ) -> RowComponents | None:
        """Build 'The Blend' row from Gold+Silver tier (Top 1-8)."""
        recipes = get_blend_recipes()
        random.shuffle(recipes)

        for recipe in recipes:
            builder = RowBuilder(features)
            if self._apply_recipe(builder, recipe, features, tier="gold_silver", exclude_keywords=exclude_keywords):
                return builder.build()

        return None

    def _build_rising_star_row(
        self, features: ExtractedFeatures, exclude_keywords: list[int] | None = None
    ) -> RowComponents | None:
        """Build 'The Rising Star' row from Silver tier (Rank 4-10)."""
        recipes = get_rising_star_recipes()
        random.shuffle(recipes)

        for recipe in recipes:
            builder = RowBuilder(features)
            if self._apply_recipe(builder, recipe, features, tier="silver", exclude_keywords=exclude_keywords):
                return builder.build()

        # Fallback: try Gold tier if Silver is empty
        for recipe in recipes:
            builder = RowBuilder(features)
            if self._apply_recipe(builder, recipe, features, tier="gold", exclude_keywords=exclude_keywords):
                return builder.build()

        return None

    def _apply_recipe(
        self,
        builder: RowBuilder,
        recipe: list[str],
        features: ExtractedFeatures,
        tier: str,
        exclude_keywords: list[int] | None = None,
    ) -> bool:
        """Apply a recipe to the builder. Returns True if successful."""
        exclude_keywords = exclude_keywords or []

        # Select sampler based on tier
        if tier == "gold":
            sampler = sample_from_gold
        elif tier == "silver":
            sampler = sample_from_silver
        else:
            sampler = sample_from_gold_silver

        for axis in recipe:
            if axis == AXIS_GENRE:
                sampled = sampler(features.genres, 1)
                if sampled:
                    builder.add_genre(sampled[0][0])

            elif axis == AXIS_KEYWORD:
                # Filter out already used keywords
                available = [
                    (k, s) for k, s in features.keywords if k not in exclude_keywords and k not in builder.used_keywords
                ]
                sampled = sampler(available, 1) if tier != "silver" else sample_from_silver(available, 1)
                if sampled:
                    builder.add_keyword(sampled[0][0])

            elif axis == AXIS_COUNTRY:
                sampled = sampler(features.countries, 1)
                if sampled:
                    builder.add_country(sampled[0][0])

            elif axis == AXIS_ERA:
                sampled = sampler(features.eras, 1)
                if sampled:
                    decade = era_to_decade(sampled[0][0])
                    if decade:
                        builder.add_era(decade)

            elif axis == AXIS_RUNTIME:
                if features.runtimes:
                    # Runtime: just pick the top one
                    builder.add_runtime(features.runtimes[0][0])

        # Check if we added enough components
        return len(builder.components.prompt_parts) >= 2

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
            row_id = build_row_id(row.to_dict())

            final_rows.append(
                RowDefinition(
                    title=title,
                    id=row_id,
                    **row.to_dict(),
                )
            )

        return final_rows
