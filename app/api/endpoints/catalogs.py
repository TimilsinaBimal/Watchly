import re

from fastapi import APIRouter, HTTPException, Response
from loguru import logger

from app.api.endpoints.manifest import get_config_id
from app.core.config import settings
from app.core.security import redact_token
from app.core.settings import UserSettings, get_default_settings
from app.services.catalog_updater import catalog_updater
from app.services.profile.integration import ProfileIntegration
from app.services.recommendation.creators import CreatorsService
from app.services.recommendation.item_based import ItemBasedService
from app.services.recommendation.theme_based import ThemeBasedService
from app.services.recommendation.top_picks import TopPicksService
from app.services.recommendation.utils import pad_to_min
from app.services.stremio.service import StremioBundle
from app.services.tmdb.service import get_tmdb_service
from app.services.token_store import token_store

MAX_RESULTS = 50
DEFAULT_MIN_ITEMS = 20
DEFAULT_MAX_ITEMS = 32

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

    # if id does not start with tt, return None
    if not cleaned.get("id", "").startswith("tt"):
        return None
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
    if id not in ["watchly.rec", "watchly.creators"] and not any(
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
                "Invalid id. Supported: 'watchly.rec', 'watchly.creators', 'watchly.theme.<params>',"
                "'watchly.item.<id>', or  specific item IDs."
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

        # Initialize services
        tmdb_service = get_tmdb_service(language=language)
        integration = ProfileIntegration(language=language)
        item_service = ItemBasedService(tmdb_service, user_settings)
        theme_service = ThemeBasedService(tmdb_service, user_settings)
        top_picks_service = TopPicksService(tmdb_service, user_settings)
        creators_service = CreatorsService(tmdb_service, user_settings)

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
        if id.startswith("tt") or any(
            id.startswith(p)
            for p in (
                "watchly.item.",
                "watchly.loved.",
                "watchly.watched.",
            )
        ):
            # Extract actual item ID
            if id.startswith("tt"):
                item_id = id
            else:
                item_id = re.sub(r"^watchly\.(item|loved|watched)\.", "", id)

            # Get watched sets
            _, watched_tmdb, watched_imdb = await integration.build_profile_from_library(
                library_items, type, bundle, auth_key
            )

            # Get genre whitelist
            whitelist = await integration.get_genre_whitelist(library_items, type, bundle, auth_key)

            # Use new item-based service
            recommendations = await item_service.get_recommendations_for_item(
                item_id=item_id,
                content_type=type,
                watched_tmdb=watched_tmdb,
                watched_imdb=watched_imdb,
                limit=max_items,
                integration=integration,
                library_items=library_items,
            )

            if len(recommendations) < min_items:
                recommendations = await pad_to_min(
                    type, recommendations, min_items, tmdb_service, user_settings, bundle, library_items, auth_key
                )
            logger.info(f"Found {len(recommendations)} recommendations for item {item_id}")

        elif id.startswith("watchly.theme."):
            # Build profile for theme-based recommendations
            profile, watched_tmdb, watched_imdb = await integration.build_profile_from_library(
                library_items, type, bundle, auth_key
            )

            # Use new theme-based service
            recommendations = await theme_service.get_recommendations_for_theme(
                theme_id=id,
                content_type=type,
                profile=profile,
                watched_tmdb=watched_tmdb,
                watched_imdb=watched_imdb,
                limit=max_items,
                integration=integration,
                library_items=library_items,
            )

            if len(recommendations) < min_items:
                recommendations = await pad_to_min(
                    type, recommendations, min_items, tmdb_service, user_settings, bundle, library_items, auth_key
                )
            logger.info(f"Found {len(recommendations)} recommendations for theme {id}")

        elif id == "watchly.creators":
            # Build profile for creators-based recommendations
            profile, watched_tmdb, watched_imdb = await integration.build_profile_from_library(
                library_items, type, bundle, auth_key
            )

            # Get genre whitelist
            whitelist = await integration.get_genre_whitelist(library_items, type, bundle, auth_key)

            if profile:
                # Use new creators service
                recommendations = await creators_service.get_recommendations_from_creators(
                    profile=profile,
                    content_type=type,
                    library_items=library_items,
                    watched_tmdb=watched_tmdb,
                    watched_imdb=watched_imdb,
                    whitelist=whitelist,
                    limit=max_items,
                )
            else:
                # No profile available, return empty
                recommendations = []

            if len(recommendations) < min_items:
                recommendations = await pad_to_min(
                    type, recommendations, min_items, tmdb_service, user_settings, bundle, library_items, auth_key
                )
            logger.info(f"Found {len(recommendations)} recommendations from creators")

        elif id == "watchly.rec":
            # Top picks - use new TopPicksService
            profile, watched_tmdb, watched_imdb = await integration.build_profile_from_library(
                library_items, type, bundle, auth_key
            )

            if profile:
                recommendations = await top_picks_service.get_top_picks(
                    profile=profile,
                    content_type=type,
                    library_items=library_items,
                    watched_tmdb=watched_tmdb,
                    watched_imdb=watched_imdb,
                    limit=max_items,
                )
            else:
                # No profile available, return empty
                recommendations = []

            if len(recommendations) < min_items:
                recommendations = await pad_to_min(
                    type, recommendations, min_items, tmdb_service, user_settings, bundle, library_items, auth_key
                )
            logger.info(f"Found {len(recommendations)} top picks for {type}")

        else:
            # Unknown catalog ID, return empty
            logger.warning(f"Unknown catalog ID: {id}")
            recommendations = []

        logger.info(f"Returning {len(recommendations)} items for {type}")
        response.headers["Cache-Control"] = "public, max-age=21600"  # 6 hours
        cleaned = [_clean_meta(m) for m in recommendations]
        # remove none values
        cleaned = [m for m in cleaned if m is not None]
        return {"metas": cleaned}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"[{redact_token(token)}] Error fetching catalog for {type}/{id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await bundle.close()
