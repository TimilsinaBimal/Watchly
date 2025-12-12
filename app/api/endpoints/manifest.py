from async_lru import alru_cache
from fastapi import HTTPException, Response
from fastapi.routing import APIRouter

from app.core.config import settings
from app.core.settings import UserSettings, get_default_settings
from app.core.version import __version__
from app.services.catalog import DynamicCatalogService
from app.services.stremio_service import StremioService
from app.services.token_store import token_store
from app.services.translation import translation_service

router = APIRouter()


def get_base_manifest(user_settings: UserSettings | None = None):
    # Default catalog config
    rec_config = None
    if user_settings:
        # Find config for 'recommended'
        rec_config = next((c for c in user_settings.catalogs if c.id == "watchly.rec"), None)

    # If disabled explicitly, don't include it.
    # If not configured (None), default to enabled.
    if rec_config and not rec_config.enabled:
        catalogs = []
    else:
        name = rec_config.name if rec_config and rec_config.name else "Top Picks for You"
        catalogs = [
            {
                "type": "movie",
                "id": "watchly.rec",
                "name": name,
                "extra": [],
            },
            {
                "type": "series",
                "id": "watchly.rec",
                "name": name,
                "extra": [],
            },
        ]

    return {
        "id": settings.ADDON_ID,
        "version": __version__,
        "name": settings.ADDON_NAME,
        "description": "Movie and series recommendations based on your Stremio library",
        "logo": "https://raw.githubusercontent.com/TimilsinaBimal/Watchly/refs/heads/main/app/static/logo.png",
        "resources": [{"name": "catalog", "types": ["movie", "series"], "idPrefixes": ["tt"]}],
        "types": ["movie", "series"],
        "idPrefixes": ["tt"],
        "catalogs": catalogs,
        "behaviorHints": {"configurable": True, "configurationRequired": False},
    }


# Cache catalog definitions for 1 hour (3600s)
@alru_cache(maxsize=1000, ttl=3600)
async def fetch_catalogs(token: str):
    credentials = await token_store.get_user_data(token)
    if not credentials:
        raise HTTPException(status_code=401, detail="Invalid or expired token. Please reconfigure the addon.")

    if credentials.get("settings"):
        user_settings = UserSettings(**credentials["settings"])
    else:
        user_settings = get_default_settings()

    stremio_service = StremioService(auth_key=credentials.get("authKey"))

    # Note: get_library_items is expensive, but we need it to determine *which* genre catalogs to show.
    library_items = await stremio_service.get_library_items()
    dynamic_catalog_service = DynamicCatalogService(stremio_service=stremio_service)

    # Base catalogs are already in manifest, these are *extra* dynamic ones
    # Pass user_settings to filter/rename
    catalogs = await dynamic_catalog_service.get_dynamic_catalogs(library_items, user_settings)

    return catalogs


def get_config_id(catalog) -> str | None:
    catalog_id = catalog.get("id", "")
    if catalog_id.startswith("watchly.theme."):
        return "watchly.theme"
    if catalog_id.startswith("watchly.loved."):
        return "watchly.loved"
    if catalog_id.startswith("watchly.watched."):
        return "watchly.watched"
    if catalog_id.startswith("watchly.item."):
        return "watchly.item"
    if catalog_id.startswith("watchly.rec"):
        return "watchly.rec"
    return catalog_id


async def _manifest_handler(response: Response, token: str):
    response.headers["Cache-Control"] = "public, max-age=86400"

    if not token:
        raise HTTPException(status_code=401, detail="Missing token. Please reconfigure the addon.")

    user_settings = None
    try:
        creds = await token_store.get_user_data(token)
        if creds.get("settings"):
            user_settings = UserSettings(**creds["settings"])
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token. Please reconfigure the addon.")

    base_manifest = get_base_manifest(user_settings)

    fetched_catalogs = await fetch_catalogs(token)

    all_catalogs = [c.copy() for c in base_manifest["catalogs"]] + [c.copy() for c in fetched_catalogs]

    translated_catalogs = []

    # translate to target language
    if user_settings and user_settings.language:
        for cat in all_catalogs:
            if cat.get("name"):
                cat["name"] = await translation_service.translate(cat["name"], user_settings.language)
                translated_catalogs.append(cat)
    else:
        translated_catalogs = all_catalogs

    if user_settings:
        order_map = {c.id: i for i, c in enumerate(user_settings.catalogs)}
        translated_catalogs.sort(key=lambda x: order_map.get(get_config_id(x), 999))

    base_manifest["catalogs"] = translated_catalogs

    return base_manifest


@router.get("/manifest.json")
async def manifest():
    manifest = get_base_manifest()
    # since user is not logged in, return empty catalogs
    manifest["catalogs"] = []
    return manifest


@router.get("/{token}/manifest.json")
async def manifest_token(response: Response, token: str):
    return await _manifest_handler(response, token)
