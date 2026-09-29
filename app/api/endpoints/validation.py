from typing import Literal

from fastapi import APIRouter, HTTPException
from loguru import logger
from pydantic import BaseModel, Field, ValidationError

from app.api.models.validation import (
    BaseValidationInput,
    BaseValidationResponse,
    PosterPreview,
    PosterPreviewInput,
    PosterRatingValidationInput,
)
from app.core.security import STORED_SECRET_SENTINEL
from app.core.settings import LLMConfig, PosterRatingConfig
from app.services.llm import llm_service
from app.services.poster_ratings.factory import PosterProvider, poster_ratings_factory
from app.services.simkl import simkl_service
from app.services.tmdb.client import TMDBClient
from app.services.token_store import token_store
from app.services.trakt import trakt_service

router = APIRouter(tags=["Validation"])


class LLMValidationInput(BaseModel):
    provider: Literal["gemini", "openai", "anthropic", "openrouter"]
    api_key: str = Field(description="API key for the provider")
    model: str | None = Field(default=None, description="Optional model id override")


@router.post("/llm/validation")
async def validate_llm_key(data: LLMValidationInput) -> BaseValidationResponse:
    """Validate the key (and model) with a minimal real generation."""
    config = LLMConfig(provider=data.provider, api_key=data.api_key.strip(), model=(data.model or "").strip() or None)
    title = await llm_service.generate_title("Genre: Action, Keyword: heist", config)
    if title:
        return BaseValidationResponse(valid=True, message=f"Key works with {config.resolved_model()}")
    return BaseValidationResponse(valid=False, message="Could not generate with this key/model")


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
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Poster rating validation failed: {str(e)}")
        return BaseValidationResponse(valid=False, message="Could not validate API key. Please try again.")


PREVIEW_TITLES = [("Interstellar", "movie", "tt0816692"), ("Breaking Bad", "series", "tt0903747")]


@router.post("/poster-rating/preview")
async def preview_custom_poster_template(payload: PosterPreviewInput) -> list[PosterPreview]:
    """Fill a custom poster template for two sample titles; the browser loads the images."""
    try:
        PosterRatingConfig(provider=PosterProvider.CUSTOM.value, url_template=payload.url_template)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=e.errors()[0]["msg"].removeprefix("Value error, "))

    api_key = payload.api_key
    if api_key == STORED_SECRET_SENTINEL:
        # The page only holds the marker for a saved key, so resolve it the way a
        # settings save would: same account, and only if it was saved for 'custom'.
        if not payload.token:
            raise HTTPException(status_code=400, detail="Log in again to preview with your saved API key.")
        user_data = await token_store.get_user_data(await token_store.resolve_alias(payload.token))
        if not user_data:
            raise HTTPException(status_code=404, detail="Account not found. Log in again.")
        stored = (user_data.get("settings") or {}).get("poster_rating") or {}
        if stored.get("provider") != PosterProvider.CUSTOM.value or not stored.get("api_key"):
            raise HTTPException(status_code=400, detail="No saved API key for the custom provider. Paste it again.")
        # A saved key only fills the saved template. Accepting any template here would
        # let whoever holds the token read the key back out of a URL they wrote.
        if payload.url_template != stored.get("url_template"):
            raise HTTPException(
                status_code=400, detail="You changed the template. Paste your API key again to preview it."
            )
        api_key = stored["api_key"]

    return [
        PosterPreview(
            title=title,
            type=media_type,
            url=poster_ratings_factory.get_poster_url(
                PosterProvider.CUSTOM,
                api_key,
                "imdb",
                imdb_id,
                url_template=payload.url_template,
                language=payload.language,
                media_type=media_type,
            ),
        )
        for title, media_type, imdb_id in PREVIEW_TITLES
    ]


@router.post("/simkl/validation")
async def validate_simkl_api_key(data: BaseValidationInput) -> BaseValidationResponse:
    try:
        response = await simkl_service.get_trending(data.api_key)
        if response:
            return BaseValidationResponse(valid=True, message="Valid API Key")
        return BaseValidationResponse(valid=False, message="Invalid API Key")
    except Exception as e:
        logger.error(f"Simkl validation failed: {str(e)}")
        return BaseValidationResponse(valid=False, message="Could not validate API key. Please try again.")


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
