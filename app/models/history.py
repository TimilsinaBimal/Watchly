from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class WatchHistoryItem(BaseModel):
    """Unified watch history item from any source (Stremio, Trakt, Simkl)."""

    imdb_id: str  # tt1234567
    type: str  # "movie" | "series"
    name: str
    rating: float | None = None  # 1-10 explicit rating (None = unrated)
    watch_count: int = 1
    completion: float = 1.0  # 0.0-1.0 (fraction of content watched)
    last_watched: datetime | None = None
    source: Literal["stremio", "trakt", "simkl"] = "stremio"


class WatchHistory(BaseModel):
    """Collection of watch history items from a single source."""

    items: list[WatchHistoryItem] = Field(default_factory=list)
    source: Literal["stremio", "trakt", "simkl"] = "stremio"

    def imdb_ids(self) -> set[str]:
        return {i.imdb_id for i in self.items}
