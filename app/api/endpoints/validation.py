from fastapi import APIRouter, HTTPException
from google import genai
from loguru import logger
from pydantic import BaseModel, Field

from app.api.models.validation import BaseValidationInput, BaseValidationResponse, PosterRatingValidationInput
from app.services.poster_ratings.factory import PosterProvider, poster_ratings_factory
from app.services.simkl import simkl_service
from app.services.tmdb.client import TMDBClient
from app.services.trakt import trakt_service

router = APIRouter(tags=["Validation"])


@router.post("/gemini/validation")
async def validate_gemini_api_key(data: BaseValidationInput) -> BaseValidationResponse:
    try:
        client = genai.Client(api_key=data.api_key.strip())
        await client.aio.models.list()
        return BaseValidationResponse(valid=True, message="Gemini API key is valid")
    except Exception as e:
        logger.debug(f"Gemini API key validation failed: {e}")
        return BaseValidationResponse(valid=False, message="Invalid Gemini API key")


@router.post("/tmdb/validation")
async def validate_tmdb_api_key(data: BaseValidationInput) -> BaseValidationResponse:
    try:
        client = TMDBClient(api_key=data.api_key.strip(), language="en-US")
        await client.get("/configuration")
        await client.close()
        return BaseValidationResponse(valid=True, message="TMDB API key is valid")
    except Exception as e:
        logger.debug(f"TMDB API key validation failed: {e}")
        return BaseValidationResponse(valid=False, message="Invalid TMDB API key")


@router.post("/poster-rating/validate")
async def validate_poster_rating_api_key(payload: PosterRatingValidationInput) -> BaseValidationResponse:
    if not payload.api_key or not payload.api_key.strip():
        return BaseValidationResponse(valid=False, message="API key cannot be empty")

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
            return BaseValidationResponse(valid=True, message="API key is valid")
        return BaseValidationResponse(valid=False, message="Invalid API key")
    except Exception as e:
        logger.error(f"Validation failed: {str(e)}")
        raise HTTPException(status_code=500, detail="Validation failed due to an internal error.")


@router.post("/simkl/validation")
async def validate_simkl_api_key(data: BaseValidationInput) -> BaseValidationResponse:
    try:
        response = await simkl_service.get_trending(data.api_key)
        if response:
            return BaseValidationResponse(valid=True, message="Valid API Key")
        return BaseValidationResponse(valid=False, message="Invalid API Key")
    except Exception as e:
        logger.error(f"Validation failed: {str(e)}")
        raise HTTPException(status_code=500, detail="Validation failed due to an internal error.")


class OAuthTokenValidationInput(BaseModel):
    access_token: str = Field(description="OAuth access token to validate")


@router.post("/trakt/validation")
async def validate_trakt_token(data: OAuthTokenValidationInput) -> BaseValidationResponse:
    """Validate a Trakt OAuth access token by calling /users/me."""
    try:
        user_info = await trakt_service.get_user_info(data.access_token)
        username = user_info.get("user", {}).get("username") or user_info.get("username", "")
        return BaseValidationResponse(valid=True, message=f"Connected as {username}")
    except Exception as e:
        logger.debug(f"Trakt token validation failed: {e}")
        return BaseValidationResponse(valid=False, message="Invalid or expired Trakt token")


@router.post("/simkl-sync/validation")
async def validate_simkl_sync_token(data: OAuthTokenValidationInput) -> BaseValidationResponse:
    """Validate a Simkl OAuth access token."""
    from app.core.config import settings as app_settings

    if not app_settings.SIMKL_CLIENT_ID:
        return BaseValidationResponse(valid=False, message="Simkl integration is not configured on this server")
    try:
        from httpx import AsyncClient

        async with AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://api.simkl.com/users/settings",
                headers={
                    "Authorization": f"Bearer {data.access_token}",
                    "simkl-api-key": app_settings.SIMKL_CLIENT_ID,
                },
                follow_redirects=True,
            )
            resp.raise_for_status()
            user_info = resp.json()
            username = user_info.get("user", {}).get("name") or "Unknown"
        return BaseValidationResponse(valid=True, message=f"Connected as {username}")
    except Exception as e:
        logger.debug(f"Simkl sync token validation failed: {e}")
        return BaseValidationResponse(valid=False, message="Invalid or expired Simkl token")
