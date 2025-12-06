from async_lru import alru_cache
from fastapi import Response
from fastapi.routing import APIRouter

from app.core.config import settings
from app.core.settings import UserSettings, decode_settings
from app.core.version import __version__
from app.services.catalog import DynamicCatalogService
from app.services.stremio_service import StremioService
from app.services.translation import translation_service
from app.utils import resolve_user_credentials

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
# Cache catalog definitions for 1 hour (3600s)
@alru_cache(maxsize=1000, ttl=3600)
async def fetch_catalogs(token: str | None = None, settings_str: str | None = None):
    if not token:
        return []

    credentials = await resolve_user_credentials(token)

    if settings_str:
        user_settings = decode_settings(settings_str)
    elif credentials.get("settings"):
        user_settings = UserSettings(**credentials["settings"])
    else:
        user_settings = None

    stremio_service = StremioService(
        username=credentials.get("username") or "",
        password=credentials.get("password") or "",
        auth_key=credentials.get("authKey"),
    )

    # Note: get_library_items is expensive, but we need it to determine *which* genre catalogs to show.
    library_items = await stremio_service.get_library_items()
    dynamic_catalog_service = DynamicCatalogService(stremio_service=stremio_service)

    # Base catalogs are already in manifest, these are *extra* dynamic ones
    # Pass user_settings to filter/rename
    catalogs = await dynamic_catalog_service.get_dynamic_catalogs(library_items, user_settings)

    return catalogs


async def _manifest_handler(response: Response, token: str | None, settings_str: str | None):
    """Stremio manifest handler."""
    # Cache manifest for 1 day (86400 seconds)
    response.headers["Cache-Control"] = "public, max-age=86400"

    user_settings = None
    if settings_str:
        user_settings = decode_settings(settings_str)
    elif token:
        try:
            creds = await resolve_user_credentials(token)
            if creds.get("settings"):
                user_settings = UserSettings(**creds["settings"])
        except Exception:
            # Fallback to defaults if token resolution fails (or let it fail later in fetch_catalogs)
            pass

    base_manifest = get_base_manifest(user_settings)

    if user_settings and user_settings.language:
        for cat in base_manifest.get("catalogs", []):
            if cat.get("name"):
                cat["name"] = await translation_service.translate(cat["name"], user_settings.language)

    if token:
        # We pass settings_str to fetch_catalogs so it can cache different versions
        # We COPY the lists to avoid modifying cached objects or base_manifest defaults
        fetched_catalogs = await fetch_catalogs(token, settings_str)

        # Create a new list with copies of all catalogs
        all_catalogs = [c.copy() for c in base_manifest["catalogs"]] + [c.copy() for c in fetched_catalogs]

        if user_settings:
            # Create a lookup for order index
            order_map = {c.id: i for i, c in enumerate(user_settings.catalogs)}

            # Sort. Items not in map go to end.
            # Extract config id from catalog id for matching with user settings
            def get_config_id(catalog):
                catalog_id = catalog.get("id", "")
                if catalog_id.startswith("watchly.theme."):
                    return "watchly.theme"
                if catalog_id.startswith("watchly.item."):
                    return "watchly.item"
                if catalog_id.startswith("watchly.rec"):
                    return "watchly.rec"
                return catalog_id

            all_catalogs.sort(key=lambda x: order_map.get(get_config_id(x), 999))

        base_manifest["catalogs"] = all_catalogs

    return base_manifest


@router.get("/manifest.json")
async def manifest_root(response: Response):
    return await _manifest_handler(response, None, None)


@router.get("/{token}/manifest.json")
async def manifest_token(response: Response, token: str):
    return await _manifest_handler(response, token, None)


@router.get("/{settings_str}/{token}/manifest.json")
async def manifest_settings(response: Response, settings_str: str, token: str):
    return await _manifest_handler(response, token, settings_str)
