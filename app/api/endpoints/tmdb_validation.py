from fastapi import APIRouter
from loguru import logger
from pydantic import BaseModel

from app.services.tmdb.client import TMDBClient

router = APIRouter(prefix="/tmdb", tags=["tmdb"])


class TmdbValidationInput(BaseModel):
    api_key: str


class TmdbValidationResponse(BaseModel):
    valid: bool
    message: str


@router.post("/validation")
async def validate_tmdb_api_key(data: TmdbValidationInput) -> TmdbValidationResponse:
    """Validate a TMDB API key by calling the configuration endpoint."""
    if not (data.api_key or "").strip():
        return TmdbValidationResponse(valid=False, message="API key is required")
    try:
        client = TMDBClient(api_key=data.api_key.strip(), language="en-US")
        # Lightweight call that requires a valid key
        await client.get("/configuration")
        await client.close()
        return TmdbValidationResponse(valid=True, message="TMDB API key is valid")
    except Exception as e:
        logger.debug(f"TMDB API key validation failed: {e}")
        return TmdbValidationResponse(valid=False, message="Invalid TMDB API key")
