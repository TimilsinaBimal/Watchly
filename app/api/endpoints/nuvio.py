"""What the browser needs to sign in to Nuvio itself.

The Nuvio connect flow runs in the browser so a Nuvio password never reaches
this server; the page only needs the backend URL and the publishable key, both
of which Nuvio publishes in its own clients.
"""

from fastapi import APIRouter

from app.services.nuvio import discover

router = APIRouter(prefix="/nuvio", tags=["Nuvio"])


@router.get("/config")
async def nuvio_config() -> dict[str, str]:
    """Backend URL and publishable key for the browser-side Nuvio sign-in."""
    backend_url, publishable_key = await discover()
    return {"backend_url": backend_url, "publishable_key": publishable_key}
