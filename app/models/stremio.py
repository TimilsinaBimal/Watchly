from typing import List, Optional
from pydantic import BaseModel


class StremioMeta(BaseModel):
    """Stremio metadata item format."""

    id: str
    type: str
    name: str
    poster: Optional[str] = None
    posterShape: Optional[str] = None
    background: Optional[str] = None
    logo: Optional[str] = None
    description: Optional[str] = None
    releaseInfo: Optional[str] = None
    year: Optional[str] = None
    imdbRating: Optional[str] = None
    genres: Optional[List[str]] = None
    website: Optional[str] = None


class StremioCatalogResponse(BaseModel):
    """Stremio catalog response format."""

    metas: List[StremioMeta]

