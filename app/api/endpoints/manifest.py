from fastapi import HTTPException, Response
from fastapi.routing import APIRouter
from loguru import logger

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


async def build_dynamic_catalogs(stremio_service: StremioService, user_settings: UserSettings) -> list[dict]:
    # Note: get_library_items is the heavy call; StremioService has its own short cache.
    library_items = await stremio_service.get_library_items()
    dynamic_catalog_service = DynamicCatalogService(
        stremio_service=stremio_service,
        language=user_settings.language,
    )
    return await dynamic_catalog_service.get_dynamic_catalogs(library_items, user_settings)


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
    response.headers["Cache-Control"] = "no-cache"

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

    # Build dynamic catalogs using a single service; get_auth_key() handles validation/refresh
    stremio_service = StremioService(
        username=creds.get("email", ""),
        password=creds.get("password", ""),
        auth_key=creds.get("authKey"),
    )
    try:
        fetched_catalogs = await build_dynamic_catalogs(
            stremio_service,
            user_settings or get_default_settings(),
        )
    except Exception as e:
        logger.warning(f"Dynamic catalog build failed: {e}")
        fetched_catalogs = []

    all_catalogs = [c.copy() for c in base_manifest["catalogs"]] + [c.copy() for c in fetched_catalogs]

    translated_catalogs = []

    # translate to target language
    if user_settings and user_settings.language:
        for cat in all_catalogs:
            if cat.get("name"):
                try:
                    cat["name"] = await translation_service.translate(cat["name"], user_settings.language)
                except Exception as e:
                    # On translation failure, keep original name and log the error
                    logger.warning(f"Failed to translate catalog name '{cat.get('name')}': {e}")
                translated_catalogs.append(cat)
    else:
        translated_catalogs = all_catalogs

    if user_settings:
        order_map = {c.id: i for i, c in enumerate(user_settings.catalogs)}
        translated_catalogs.sort(key=lambda x: order_map.get(get_config_id(x), 999))

    # Safety fallback respecting user settings:
    # - If the final list is empty AND user's base config allows 'watchly.rec',
    #   expose the base recommendation rows (so users don't see an empty addon).
    # - If the user explicitly disabled 'watchly.rec' (or disabled all rows),
    #   DO NOT add fallback rows; keep it empty to honor their choice.
    if not translated_catalogs:
        fallback_base = get_base_manifest(user_settings)
        if fallback_base.get("catalogs"):
            base_manifest["catalogs"] = fallback_base["catalogs"]
        else:
            base_manifest["catalogs"] = []
    else:
        base_manifest["catalogs"] = translated_catalogs

    # Debug headers (counts) to help diagnose empty-manifest issues in production
    try:
        response.headers["X-Base-Catalogs"] = str(len(get_base_manifest(user_settings)["catalogs"]))
        response.headers["X-Dynamic-Catalogs"] = str(len(fetched_catalogs))
        response.headers["X-Final-Catalogs"] = str(len(base_manifest.get("catalogs", [])))
    except Exception as e:
        logger.warning(f"Failed to set debug headers: {e}")

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
