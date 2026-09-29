from typing import Literal

from pydantic import BaseModel, Field

from app.core.security import TOKEN_PATTERN


class BaseValidationInput(BaseModel):
    api_key: str = Field(description="API key to validate")


class BaseValidationResponse(BaseModel):
    valid: bool
    message: str


class PosterRatingValidationInput(BaseValidationInput):
    provider: str = Field(description="Provider name: 'rpdb' or 'top_posters'")


class PosterPreviewInput(BaseModel):
    url_template: str
    api_key: str | None = Field(default=None, description="The key, or the stored-secret marker for the saved one")
    language: str = Field(default="en-US", max_length=16)
    # Only needed with the marker, to find whose saved key to use.
    token: str | None = Field(default=None, pattern=TOKEN_PATTERN.pattern)


class PosterPreview(BaseModel):
    title: str
    type: Literal["movie", "series"]
    url: str
