from fastapi import APIRouter
from loguru import logger

from app.services.token_store import token_store

router = APIRouter(tags=["health"])


@router.get("/health", summary="Simple readiness probe")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/metrics", summary="Runtime metrics (lightweight)")
async def metrics() -> dict:
    """Return lightweight runtime metrics useful for diagnosing Redis connection growth."""
    try:
        client = await token_store._get_client()
    except Exception as exc:
        logger.warning(f"Failed to fetch Redis client for metrics: {exc}")
        return {"redis": "unavailable"}

    metrics: dict = {}
    try:
        info = await client.info(section="clients")
        metrics["redis_connected_clients"] = int(info.get("connected_clients", 0))
    except Exception as exc:
        logger.warning(f"Failed to read Redis INFO clients: {exc}")
        metrics["redis_connected_clients"] = "error"

    try:
        metrics["per_request_redis_calls_last"] = token_store.get_call_count()
    except Exception:
        metrics["per_request_redis_calls_last"] = "error"

    return metrics
