from abc import ABC, abstractmethod

from pydantic import BaseModel


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


class RowStrategy(ABC):
    """
    Interface for a row generation strategy.
    """

    @abstractmethod
    async def generate(self, profile, content_type: str) -> list[RowDefinition]:
        """
        Generate one or more rows based on the profile.
        """
        pass
