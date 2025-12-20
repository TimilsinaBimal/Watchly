import re

from fastapi import APIRouter, HTTPException, Response
from loguru import logger

from app.api.endpoints.manifest import get_config_id
from app.core.config import settings
from app.core.security import redact_token
from app.core.settings import UserSettings, get_default_settings
from app.services.catalog_updater import catalog_updater
from app.services.recommendation.engine import RecommendationEngine
from app.services.stremio.service import StremioBundle
from app.services.token_store import token_store

MAX_RESULTS = 50
DEFAULT_MIN_ITEMS = 20
DEFAULT_MAX_ITEMS = 32
SOURCE_ITEMS_LIMIT = 10

router = APIRouter()


def _clean_meta(meta: dict) -> dict:
    """Return a sanitized Stremio meta object without internal fields.

    Keeps only public keys and drops internal scoring/IDs/keywords/cast, etc.
    """
    allowed = {
        "id",
        "type",
        "name",
        "poster",
        "background",
        "description",
        "releaseInfo",
        "imdbRating",
        "genres",
        "runtime",
    }
    cleaned = {k: v for k, v in meta.items() if k in allowed}
    # Drop empty values
    cleaned = {k: v for k, v in cleaned.items() if v not in (None, "", [], {}, ())}
    return cleaned


@router.get("/{token}/catalog/{type}/{id}.json")
async def get_catalog(type: str, id: str, response: Response, token: str):
    if not token:
        raise HTTPException(
            status_code=400,
            detail="Missing credentials token. Please open Watchly from a configured manifest URL.",
        )

    if type not in ["movie", "series"]:
        logger.warning(f"Invalid type: {type}")
        raise HTTPException(status_code=400, detail="Invalid type. Use 'movie' or 'series'")

    # Supported IDs now include dynamic themes and item-based rows
    if id != "watchly.rec" and not any(
        id.startswith(p)
        for p in (
            "tt",
            "watchly.theme.",
            "watchly.item.",
            "watchly.loved.",
            "watchly.watched.",
        )
    ):
        logger.warning(f"Invalid id: {id}")
        raise HTTPException(
            status_code=400,
            detail=(  #
                "Invalid id. Supported: 'watchly.rec', 'watchly.theme.<params>', 'watchly.item.<id>', or"
                " specific item IDs."
            ),
        )

    logger.info(f"[{redact_token(token)}] Fetching catalog for {type} with id {id}")

    credentials = await token_store.get_user_data(token)
    if not credentials:
        raise HTTPException(status_code=401, detail="Invalid or expired token. Please reconfigure the addon.")

    # Trigger lazy update if needed
    if settings.AUTO_UPDATE_CATALOGS:
        await catalog_updater.trigger_update(token, credentials)

    bundle = StremioBundle()
    try:
        # 1. Resolve Auth Key (with potential fallback to login)
        auth_key = credentials.get("authKey")
        email = credentials.get("email")
        password = credentials.get("password")

        is_valid = False
        if auth_key:
            try:
                await bundle.auth.get_user_info(auth_key)
                is_valid = True
            except Exception:
                pass

        if not is_valid and email and password:
            try:
                auth_key = await bundle.auth.login(email, password)
                credentials["authKey"] = auth_key
                await token_store.update_user_data(token, credentials)
            except Exception as e:
                logger.error(f"Failed to refresh auth key during catalog fetch: {e}")

        if not auth_key:
            raise HTTPException(status_code=401, detail="Stremio session expired. Please reconfigure.")

        # 2. Extract settings from credentials
        settings_dict = credentials.get("settings", {})
        user_settings = UserSettings(**settings_dict) if settings_dict else get_default_settings()
        language = user_settings.language if user_settings else "en-US"

        # 3. Fetch library once per request and reuse across recommendation paths
        library_items = await bundle.library.get_library_items(auth_key)
        engine = RecommendationEngine(
            stremio_service=bundle,
            language=language,
            user_settings=user_settings,
            token=token,
            library_data=library_items,
        )

        # Resolve per-catalog limits (min/max)
        def _get_limits() -> tuple[int, int]:
            try:
                cfg_id = get_config_id({"id": id})
            except Exception:
                cfg_id = id
            try:
                cfg = next((c for c in user_settings.catalogs if c.id == cfg_id), None)
                if cfg and hasattr(cfg, "min_items") and hasattr(cfg, "max_items"):
                    return int(cfg.min_items or DEFAULT_MIN_ITEMS), int(cfg.max_items or DEFAULT_MAX_ITEMS)
            except Exception:
                pass
            return DEFAULT_MIN_ITEMS, DEFAULT_MAX_ITEMS

        min_items, max_items = _get_limits()
        # Enforce caps: min_items <= 20, max_items <= 32 and max >= min
        try:
            min_items = max(1, min(DEFAULT_MIN_ITEMS, int(min_items)))
            max_items = max(min_items, min(DEFAULT_MAX_ITEMS, int(max_items)))
        except (ValueError, TypeError):
            logger.warning(
                "Invalid min/max items values. Falling back to defaults. "
                f"min_items={min_items}, max_items={max_items}"
            )
            min_items, max_items = DEFAULT_MIN_ITEMS, DEFAULT_MAX_ITEMS

        # Handle item-based recommendations
        if id.startswith("tt"):
            engine.per_item_limit = max_items
            recommendations = await engine.get_recommendations_for_item(item_id=id, media_type=type)
            if len(recommendations) < min_items:
                recommendations = await engine.pad_to_min(type, recommendations, min_items)
            logger.info(f"Found {len(recommendations)} recommendations for {id}")

        elif any(
            id.startswith(p)
            for p in (
                "watchly.item.",
                "watchly.loved.",
                "watchly.watched.",
            )
        ):
            # Extract actual item ID (tt... or tmdb:...)
            item_id = re.sub(r"^watchly\.(item|loved|watched)\.", "", id)
            engine.per_item_limit = max_items
            recommendations = await engine.get_recommendations_for_item(item_id=item_id, media_type=type)
            if len(recommendations) < min_items:
                recommendations = await engine.pad_to_min(type, recommendations, min_items)
            logger.info(f"Found {len(recommendations)} recommendations for item {item_id}")

        elif id.startswith("watchly.theme."):
            recommendations = await engine.get_recommendations_for_theme(
                theme_id=id, content_type=type, limit=max_items
            )
            if len(recommendations) < min_items:
                recommendations = await engine.pad_to_min(type, recommendations, min_items)
            logger.info(f"Found {len(recommendations)} recommendations for theme {id}")

        else:
            recommendations = await engine.get_recommendations(
                content_type=type, source_items_limit=SOURCE_ITEMS_LIMIT, max_results=max_items
            )
            if len(recommendations) < min_items:
                recommendations = await engine.pad_to_min(type, recommendations, min_items)
            logger.info(f"Found {len(recommendations)} recommendations for {type}")

        logger.info(f"Returning {len(recommendations)} items for {type}")
        # Avoid serving stale results; revalidate on each request
        response.headers["Cache-Control"] = "no-cache"
        cleaned = [_clean_meta(m) for m in recommendations]
        return {"metas": cleaned}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"[{redact_token(token)}] Error fetching catalog for {type}/{id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await bundle.close()
