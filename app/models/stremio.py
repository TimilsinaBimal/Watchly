from pydantic import BaseModel


class StremioMeta(BaseModel):
    """Stremio metadata item format."""

    id: str
    type: str
    name: str
    poster: str | None = None
    posterShape: str | None = None
    background: str | None = None
    logo: str | None = None
    description: str | None = None
    releaseInfo: str | None = None
    year: str | None = None
    imdbRating: str | None = None
    genres: list[str] | None = None
    website: str | None = None


class StremioCatalogResponse(BaseModel):
    """Stremio catalog response format."""

    metas: list[StremioMeta]
