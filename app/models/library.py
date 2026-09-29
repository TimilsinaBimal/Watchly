from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class StremioState(BaseModel):
    """Represents the user state for a library item."""

    lastWatched: datetime | None = None
    timeWatched: int = 0
    overallTimeWatched: int = 0
    timesWatched: int = 0
    flaggedWatched: int = 0
    duration: int = 0
    watched: str | None = None
    season: int = 0
    episode: int = 0

    @field_validator("lastWatched", mode="before")
    @classmethod
    def parse_last_watched(cls, v):
        if isinstance(v, str):
            try:
                return datetime.fromisoformat(v)
            except ValueError:
                return None
        return v


class StremioLibraryItem(BaseModel):
    """Represents a raw item from Stremio library."""

    id: str = Field(..., alias="_id")
    type: str
    name: str
    state: StremioState = Field(default_factory=StremioState)
    mtime: str = Field(default="", alias="_mtime")
    poster: str | None = None
    temp: bool
    removed: bool

    # Enriched fields (not in raw Stremio JSON, added by our service)
    is_loved: bool = Field(default=False, alias="_is_loved")
    is_liked: bool = Field(default=False, alias="_is_liked")

    class Config:
        populate_by_name = True

    @property
    def last_interaction(self) -> datetime | None:
        """When the user last watched the item, else when Stremio last touched it."""
        if self.state.lastWatched:
            return self.state.lastWatched
        try:
            return datetime.fromisoformat(self.mtime) if self.mtime else None
        except ValueError:
            return None


class LibraryCollection(BaseModel):
    """Typed container for categorized library items.

    This is the single shape that flows through the app. When Trakt/Simkl
    history providers are added, they produce the same LibraryCollection
    so the rest of the app doesn't care about the source.
    """

    loved: list[StremioLibraryItem] = []
    liked: list[StremioLibraryItem] = []
    watched: list[StremioLibraryItem] = []
    added: list[StremioLibraryItem] = []
    source: str = "stremio"

    def all_items(self) -> list[StremioLibraryItem]:
        return self.loved + self.liked + self.watched + self.added

    def for_type(self, content_type: str) -> "LibraryCollection":
        return LibraryCollection(
            loved=[i for i in self.loved if i.type == content_type],
            liked=[i for i in self.liked if i.type == content_type],
            watched=[i for i in self.watched if i.type == content_type],
            added=[i for i in self.added if i.type == content_type],
            source=self.source,
        )

    def all_imdb_ids(self) -> set[str]:
        return {i.id for i in self.all_items() if i.id.startswith("tt")}

    def is_empty(self) -> bool:
        return not any([self.loved, self.liked, self.watched, self.added])
