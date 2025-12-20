from fastapi import HTTPException, Response
from fastapi.routing import APIRouter
from loguru import logger

from app.core.config import settings
from app.core.settings import UserSettings, get_default_settings
from app.core.version import __version__
from app.services.catalog import DynamicCatalogService
from app.services.catalog_updater import get_config_id
from app.services.stremio.service import StremioBundle
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
        enabled_movie = getattr(rec_config, "enabled_movie", True) if rec_config else True
        enabled_series = getattr(rec_config, "enabled_series", True) if rec_config else True

        catalogs = []
        if enabled_movie:
            catalogs.append(
                {
                    "type": "movie",
                    "id": "watchly.rec",
                    "name": name,
                    "extra": [],
                }
            )
        if enabled_series:
            catalogs.append(
                {
                    "type": "series",
                    "id": "watchly.rec",
                    "name": name,
                    "extra": [],
                }
            )

    return {
        "id": settings.ADDON_ID,
        "version": __version__,
        "name": settings.ADDON_NAME,
        "description": "Movie and series recommendations based on your Stremio library",
        "logo": "https://raw.githubusercontent.com/TimilsinaBimal/Watchly/refs/heads/main/app/static/logo.png",
        "background": "https://raw.githubusercontent.com/TimilsinaBimal/Watchly/refs/heads/main/app/static/cover.png",
        "resources": ["catalog"],
        "types": ["movie", "series"],
        "idPrefixes": ["tt"],
        "catalogs": catalogs,
        "behaviorHints": {"configurable": True, "configurationRequired": False},
        "stremioAddonsConfig": {
            "issuer": "https://stremio-addons.net",
            "signature": "eyJhbGciOiJkaXIiLCJlbmMiOiJBMTI4Q0JDLUhTMjU2In0..ycLGL5WUjggv7PxKPqMLYQ.Y_cD-8wqoXqENdXbFmR1-Si39NtqBlsxEDdrEO0deciilBsWWAlPIglx85XFE4ScSfSqzNxrCZUjHjWWIb2LdcFuvE1RVBrFsUBXgbs5eQknnEL617pFtCWNh0bi37Xv.zYhJ87ZqcYZMRfxLY0bSGQ",  # noqa
        },
    }


async def build_dynamic_catalogs(bundle: StremioBundle, auth_key: str, user_settings: UserSettings) -> list[dict]:
    # Fetch library using bundle directly
    library_items = await bundle.library.get_library_items(auth_key)
    dynamic_catalog_service = DynamicCatalogService(
        language=user_settings.language,
    )
    return await dynamic_catalog_service.get_dynamic_catalogs(library_items, user_settings)


async def _manifest_handler(response: Response, token: str):
    response.headers["Cache-Control"] = "public, max-age=300"  # 5 minutes

    if not token:
        raise HTTPException(status_code=401, detail="Missing token. Please reconfigure the addon.")

    user_settings = None
    try:
        creds = await token_store.get_user_data(token)
        if creds and creds.get("settings"):
            user_settings = UserSettings(**creds["settings"])
    except Exception as e:
        logger.error(f"[{token}] Error loading user data from token store: {e}")
        raise HTTPException(status_code=401, detail="Invalid token session. Please reconfigure.")

    if not creds:
        raise HTTPException(status_code=401, detail="Token not found. Please reconfigure the addon.")

    base_manifest = get_base_manifest(user_settings)

    bundle = StremioBundle()
    fetched_catalogs = []
    try:
        # Resolve Auth Key (with potential fallback to login)
        auth_key = creds.get("authKey")
        email = creds.get("email")
        password = creds.get("password")

        is_valid = False
        if auth_key:
            try:
                await bundle.auth.get_user_info(auth_key)
                is_valid = True
            except Exception as e:
                logger.debug(f"Auth key check failed for {email or 'unknown'}: {e}")
                pass

        if not is_valid and email and password:
            try:
                auth_key = await bundle.auth.login(email, password)
                # Update store
                creds["authKey"] = auth_key
                await token_store.update_user_data(token, creds)
            except Exception as e:
                logger.error(f"Failed to refresh auth key during manifest fetch: {e}")

        if auth_key:
            fetched_catalogs = await build_dynamic_catalogs(
                bundle,
                auth_key,
                user_settings or get_default_settings(),
            )
    except Exception as e:
        logger.exception(f"[{token}] Dynamic catalog build failed: {e}")
        fetched_catalogs = []
    finally:
        await bundle.close()

    all_catalogs = [c.copy() for c in base_manifest["catalogs"]] + [c.copy() for c in fetched_catalogs]

    translated_catalogs = []

    # translate to target language
    if user_settings and user_settings.language:
        for cat in all_catalogs:
            if cat.get("name"):
                try:
                    cat["name"] = await translation_service.translate(cat["name"], user_settings.language)
                except Exception as e:
                    logger.warning(f"Failed to translate catalog name '{cat.get('name')}': {e}")
                translated_catalogs.append(cat)
    else:
        translated_catalogs = all_catalogs

    if user_settings:
        order_map = {c.id: i for i, c in enumerate(user_settings.catalogs)}
        translated_catalogs.sort(key=lambda x: order_map.get(get_config_id(x), 999))

    if translated_catalogs:
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
