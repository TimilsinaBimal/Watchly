import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from app.core.config import settings
from app.core.settings import resolve_tmdb_api_key
from app.services.catalog_updater import catalog_updater
from app.services.context import extract_settings
from app.services.tmdb.genre import movie_genres, series_genres
from app.services.tmdb.service import get_tmdb_service
from app.services.token_store import token_store
from app.services.user_cache import user_cache


class DashboardService:
    """Read-only view of a user's install plus a manual refresh.

    Everything here is keyed on the manifest token alone (the existing trust model)
    and deliberately exposes no secrets — no passwords, auth keys, or API keys.
    """

    async def get_data(self, token: str) -> dict[str, Any] | None:
        token = await token_store.resolve_alias(token)
        credentials = await token_store.get_user_data(token)
        if not credentials:
            return None

        user_settings = extract_settings(credentials)
        host = settings.HOST_NAME.rstrip("/")
        tmdb = get_tmdb_service(language=user_settings.language, api_key=resolve_tmdb_api_key(user_settings))

        profiles = {ct: await self._profile_summary(token, ct, tmdb) for ct in ("movie", "series")}

        # Library counts come from the cached collection; null when it hasn't been
        # built yet (the dashboard's catalog rows trigger that build on first open).
        library = await user_cache.get_library_items(token)
        library_stats = (
            {
                "total": len(library.all_items()),
                "loved": len(library.loved),
                "liked": len(library.liked),
                "watched": len(library.watched),
            }
            if library
            else None
        )

        return {
            "manifest_url": f"{host}/{token}/manifest.json",
            "settings": {
                "language": user_settings.language,
                "popularity": user_settings.popularity,
                "year_min": user_settings.year_min,
                "year_max": user_settings.year_max,
                "sorting_order": user_settings.sorting_order,
            },
            "sources": {
                "active": user_settings.watch_history_source,
                "trakt": bool(user_settings.trakt_access_token),
                "simkl": bool(user_settings.simkl_access_token),
            },
            "stats": {
                "library": library_stats,
                "active_catalogs": sum(1 for c in user_settings.catalogs if c.enabled),
                "last_refresh": credentials.get("last_updated"),
            },
            "profiles": profiles,
        }

    async def _profile_summary(self, token: str, content_type: str, tmdb: Any) -> dict[str, Any] | None:
        profile = await user_cache.get_profile(token, content_type)
        if not profile:
            return None

        genre_map = movie_genres if content_type == "movie" else series_genres
        genres = [genre_map[g] for g, _ in profile.get_top_genres(limit=6) if g in genre_map]

        keywords, directors, cast = await asyncio.gather(
            self._resolve_names(tmdb.get_keyword_details, [k for k, _ in profile.get_top_keywords(limit=6)]),
            self._resolve_names(tmdb.get_person_details, [d for d, _ in profile.get_top_directors(limit=6)]),
            self._resolve_names(tmdb.get_person_details, [c for c, _ in profile.get_top_cast(limit=6)]),
        )

        return {
            "last_updated": profile.last_updated.isoformat() if profile.last_updated else None,
            "items": len(profile.processed_items),
            "genres": genres,
            "keywords": keywords,
            "directors": directors,
            "cast": cast,
            "eras": [e for e, _ in profile.get_top_eras(limit=4)],
            "countries": [c for c, _ in profile.get_top_countries(limit=5)],
        }

    @staticmethod
    async def _resolve_names(fetch: Callable[[int], Awaitable[dict]], ids: list[int]) -> list[str]:
        """Resolve TMDB ids to display names, dropping any that fail to look up."""

        async def one(item_id: int) -> str | None:
            try:
                return (await fetch(item_id)).get("name")
            except Exception:
                return None

        names = await asyncio.gather(*(one(i) for i in ids))
        return [n for n in names if n]

    async def refresh(self, token: str) -> bool:
        """Drop the user's cached data so the next request rebuilds fresh, and warm
        the catalogs in the background. Returns False if the token is unknown."""
        token = await token_store.resolve_alias(token)
        credentials = await token_store.get_user_data(token)
        if not credentials:
            return False

        await user_cache.invalidate_all_user_data(token)
        await catalog_updater.trigger_update(token, credentials)
        return True


dashboard_service = DashboardService()
