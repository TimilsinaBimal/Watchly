from fastapi import APIRouter, HTTPException

from app.core.security import TOKEN_PATTERN
from app.services.token_store import token_store
from app.services.warmup import warmup_service

router = APIRouter(tags=["Status"])


@router.get("/{token}/status")
async def warm_status(token: str):
    """Warm-up progress for an account, polled by the configure page.

    Deliberately cheap: one Redis read, no credential decrypt and no library work,
    because it is hit every couple of seconds while a warm-up runs.
    """
    if not TOKEN_PATTERN.match(token):
        raise HTTPException(status_code=400, detail="Malformed token.")

    return await warmup_service.get_status(await token_store.resolve_alias(token))
