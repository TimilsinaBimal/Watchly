from fastapi import APIRouter, HTTPException
from loguru import logger
from pydantic import BaseModel, Field

from app.services.poster_ratings.factory import PosterProvider, poster_ratings_factory

router = APIRouter(prefix="/poster-rating", tags=["poster-rating"])


class ValidateApiKeyRequest(BaseModel):
    provider: str = Field(description="Provider name: 'rpdb' or 'top_posters'")
    api_key: str = Field(description="API key to validate")


class ValidateApiKeyResponse(BaseModel):
    valid: bool
    message: str | None = None


@router.post("/validate", response_model=ValidateApiKeyResponse)
async def validate_api_key(payload: ValidateApiKeyRequest) -> ValidateApiKeyResponse:
    """Validate a poster rating provider API key."""
    if not payload.api_key or not payload.api_key.strip():
        return ValidateApiKeyResponse(valid=False, message="API key cannot be empty")

    try:
        provider_enum = PosterProvider(payload.provider)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid provider: {payload.provider}")

    try:
        if provider_enum == PosterProvider.RPDB:
            is_valid = await poster_ratings_factory.rpdb_service.validate_api_key(payload.api_key.strip())
        elif provider_enum == PosterProvider.TOP_POSTERS:
            is_valid = await poster_ratings_factory.top_posters_service.validate_api_key(payload.api_key.strip())
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported provider: {payload.provider}")

        if is_valid:
            return ValidateApiKeyResponse(valid=True, message="API key is valid")
        else:
            return ValidateApiKeyResponse(valid=False, message="Invalid API key")
    except Exception as e:
        logger.error(f"Validation failed: {str(e)}")
        return ValidateApiKeyResponse(valid=False, message="Validation failed due to an internal error.")
