from fastapi import APIRouter
from pydantic import BaseModel

from app.services.simkl import simkl_service

router = APIRouter(prefix="/simkl", tags=["simkl"])


class SimklValidationInput(BaseModel):
    api_key: str


class SimklValidationResponse(BaseModel):
    valid: bool
    message: str


@router.post("/validation")
async def validate_simkl_api_key(data: SimklValidationInput) -> SimklValidationResponse:
    response = await simkl_service.get_trending(data.api_key)
    if response:
        return SimklValidationResponse(valid=True, message="key valid")
    return SimklValidationResponse(valid=False, message="key invalid")
