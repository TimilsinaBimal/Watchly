from datetime import datetime, timezone

from app.core.settings import CatalogConfig, UserSettings
from app.services.rows.generator import RowGeneratorService
from app.services.scoring import ScoringService
from app.services.stremio import StremioService
from app.services.tmdb import get_tmdb_service
from app.services.user_profile import UserProfileService


class CatalogRowBuilder:
    @staticmethod
    def build_entry(item, label, config_id):
        item_id = item.get("_id", "")
        if config_id in ["watchly.item", "watchly.loved", "watchly.watched"] or (
            item_id.startswith("tt") and config_id in ["watchly.loved", "watchly.watched"]
        ):
            catalog_id = f"{config_id}.{item_id}"
        else:
            catalog_id = item_id

        # Robust label fallback
        if not label:
            if "loved" in config_id:
                label = "Favorite"
            elif "watched" in config_id:
                label = "Recently Watched"
            else:
                label = "Because you watched"

        return {
            "type": "series" if item.get("type") in ["tv", "series"] else "movie",
            "id": catalog_id,
            "name": f"{label} {item.get('name') or ''}".strip(),
            "extra": [],
        }

    @staticmethod
    def get_sort_date(item):
        state = item.get("state") or {}
        val = state.get("lastWatched")
        if val:
            try:
                if isinstance(val, str):
                    return datetime.fromisoformat(val.replace("Z", "+00:00"))
                return val
            except (ValueError, TypeError):
                pass

        val = item.get("_mtime")
        if val:
            try:
                return datetime.fromisoformat(str(val).replace("Z", "+00:00"))
            except (ValueError, TypeError):
                pass

        return datetime.min.replace(tzinfo=timezone.utc)


class DynamicCatalogService:
    def __init__(self, stremio_service: StremioService, language: str = "en-US"):
        self.stremio_service = stremio_service
        self.tmdb_service = get_tmdb_service(language=language)
        self.scoring_service = ScoringService()
        self.user_profile_service = UserProfileService(language=language)
        self.row_generator = RowGeneratorService(tmdb_service=self.tmdb_service)

    async def get_dynamic_catalogs(self, library_items: dict, user_settings: UserSettings | None = None) -> list[dict]:
        catalogs = []

        # 1. Theme Based
        theme_config = (
            next((c for c in user_settings.catalogs if c.id == "watchly.theme"), None) if user_settings else None
        )
        if not theme_config or theme_config.enabled:
            catalogs.extend(await self._generate_theme_catalogs(library_items, user_settings))

        # 2. Item Based Configs
        loved_config, watched_config = self._resolve_configs(user_settings)

        # 3. Add Item Based Rows
        for ctype in ["movie", "series"]:
            self._add_item_rows(catalogs, library_items, ctype, loved_config, watched_config)

        return catalogs

    async def _generate_theme_catalogs(self, library_items, user_settings):
        catalogs = []
        all_items = library_items.get("loved", []) + library_items.get("watched", [])
        unique_items = {item["_id"]: item for item in all_items}

        # Revert to Focused History (30 items) for stronger personalization
        sorted_history = sorted(unique_items.values(), key=CatalogRowBuilder.get_sort_date, reverse=True)[:30]
        scored_objects = [self.scoring_service.process_item(i) for i in sorted_history]

        for ctype in ["movie", "series"]:
            excl = getattr(user_settings, f"excluded_{ctype}_genres", []) if user_settings else []
            if excl:
                excl = [int(g) for g in excl if str(g).isdigit()]
            else:
                excl = []

            profile = await self.user_profile_service.build_user_profile(
                scored_objects, content_type=ctype, excluded_genres=excl
            )
            rows = await self.row_generator.generate_rows(profile, ctype)

            for row in rows:
                catalogs.append({"type": ctype, "id": row.id, "name": row.title, "extra": []})

        return catalogs

    def _resolve_configs(self, user_settings):
        # Default starting point
        loved = CatalogConfig(id="watchly.loved", name=None, enabled=True)
        watched = CatalogConfig(id="watchly.watched", name=None, enabled=True)

        if not user_settings:
            return loved, watched

        # Try to find existing configs
        found_loved = next((c for c in user_settings.catalogs if c.id == "watchly.loved"), None)
        found_watched = next((c for c in user_settings.catalogs if c.id == "watchly.watched"), None)

        if found_loved:
            loved = found_loved
        if found_watched:
            watched = found_watched

        # Migration logic for old 'watchly.item'
        if not found_loved and not found_watched:
            old = next((c for c in user_settings.catalogs if c.id == "watchly.item"), None)
            if old:
                loved.enabled = old.enabled
                watched.enabled = old.enabled

        return loved, watched

    def _add_item_rows(self, catalogs, library_items, ctype, loved_cfg, watched_cfg):
        last_loved_id = None

        if loved_cfg and loved_cfg.enabled:
            items = [i for i in library_items.get("loved", []) if i.get("type") == ctype]
            items.sort(key=CatalogRowBuilder.get_sort_date, reverse=True)
            if items:
                last_loved = items[0]
                last_loved_id = last_loved.get("_id")
                catalogs.append(CatalogRowBuilder.build_entry(last_loved, loved_cfg.name, "watchly.loved"))

        if watched_cfg and watched_cfg.enabled:
            # Try in_progress first (Continue Watching)
            prog_items = [i for i in library_items.get("in_progress", []) if i.get("type") == ctype]
            prog_items.sort(key=CatalogRowBuilder.get_sort_date, reverse=True)

            last_watched = None
            if prog_items:
                last_watched = prog_items[0]
                label = watched_cfg.name or "Continue Watching"
            else:
                # Fallback to last finished item
                items = [i for i in library_items.get("watched", []) if i.get("type") == ctype]
                items.sort(key=CatalogRowBuilder.get_sort_date, reverse=True)
                for item in items:
                    if last_loved_id and item.get("_id") == last_loved_id:
                        continue
                    last_watched = item
                    break
                label = watched_cfg.name or ("Recently Watched" if ctype == "movie" else "Past Series")

            if last_watched:
                catalogs.append(CatalogRowBuilder.build_entry(last_watched, label, "watchly.watched"))
