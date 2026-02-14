from pydantic import BaseModel, Field


class BaseValidationInput(BaseModel):
    api_key: str = Field(description="API key to validate")


class BaseValidationResponse(BaseModel):
    valid: bool
    message: str


class PosterRatingValidationInput(BaseValidationInput):
    provider: str = Field(description="Provider name: 'rpdb' or 'top_posters'")
