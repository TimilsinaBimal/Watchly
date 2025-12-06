from pydantic import BaseModel, Field


class SparseVector(BaseModel):
    """
    Represents a sparse vector where keys are feature IDs and values are weights.
    For countries, keys can be string codes (hashed or mapped to int if strictly int keys needed,
    but let's check if we can use str keys or if we stick to int.
    Original SparseVector uses `dict[int, float]`.
    TMDB country codes are strings (e.g. "US").
    We can either map them to ints or change the model to support str keys.
    Let's update the model to support string keys for versatility, or keep int and hash strings.
    However, for Pydantic and JSON, string keys are native.
    Let's change keys to string/int union or just strings (since ints are valid dict keys too).
    Actually, since `genres` IDs are ints, let's allow both or specific types.
    For simplicity, let's stick to `dict[str, float]` since JSON keys are strings anyway.
    But wait, existing code uses ints for IDs.
    Let's make a separate StringSparseVector or just genericize it.
    """

    values: dict[int, float] = Field(default_factory=dict)

    def normalize(self):
        """Normalize values to 0-1 range based on the maximum value."""
        if not self.values:
            return

        max_val = max(self.values.values())
        if max_val > 0:
            for k in self.values:
                self.values[k] = round(self.values[k] / max_val, 4)

    def get_top_features(self, limit: int = 5) -> list[tuple[int, float]]:
        """Return top N features by weight."""
        sorted_items = sorted(self.values.items(), key=lambda x: x[1], reverse=True)
        return sorted_items[:limit]


class StringSparseVector(BaseModel):
    """
    Sparse vector for string-based features (like Country Codes).
    """

    values: dict[str, float] = Field(default_factory=dict)

    def normalize(self):
        if not self.values:
            return
        max_val = max(self.values.values())
        if max_val > 0:
            for k in self.values:
                self.values[k] = round(self.values[k] / max_val, 4)

    def get_top_features(self, limit: int = 5) -> list[tuple[str, float]]:
        sorted_items = sorted(self.values.items(), key=lambda x: x[1], reverse=True)
        return sorted_items[:limit]


class UserTasteProfile(BaseModel):
    """
    The complete user taste profile consisting of multiple sparse vectors.
    """

    genres: SparseVector = Field(default_factory=SparseVector)
    keywords: SparseVector = Field(default_factory=SparseVector)
    cast: SparseVector = Field(default_factory=SparseVector)
    crew: SparseVector = Field(default_factory=SparseVector)
    years: SparseVector = Field(default_factory=SparseVector)
    countries: StringSparseVector = Field(default_factory=StringSparseVector)

    def normalize_all(self):
        """Normalize all component vectors."""
        self.genres.normalize()
        self.keywords.normalize()
        self.cast.normalize()
        self.crew.normalize()
        self.years.normalize()
        self.countries.normalize()

    def get_top_genres(self, limit: int = 3) -> list[tuple[int, float]]:
        return self.genres.get_top_features(limit)

    def get_top_keywords(self, limit: int = 5) -> list[tuple[int, float]]:
        return self.keywords.get_top_features(limit)

    def get_top_crew(self, limit: int = 2) -> list[tuple[int, float]]:
        return self.crew.get_top_features(limit)

    def get_top_countries(self, limit: int = 2) -> list[tuple[str, float]]:
        return self.countries.get_top_features(limit)

    def get_top_year(self, limit: int = 1) -> list[tuple[int, float]]:
        return self.years.get_top_features(limit)
