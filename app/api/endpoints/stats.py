from fastapi import APIRouter

from app.api.models.stats import StatsResponse
from app.services.token_store import token_store

router = APIRouter(tags=["Stats"])


@router.get("/stats")
async def get_stats() -> StatsResponse:
    return StatsResponse(total_users=await token_store.count_users())
