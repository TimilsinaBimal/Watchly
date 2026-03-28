from app.models.library import LibraryCollection
from app.models.profile import ScoredItem
from app.services.profile.constants import SMART_SAMPLING_MAX_ITEMS
from app.services.profile.scoring import ScoringService


def sample_items(
    library_items: LibraryCollection,
    content_type: str,
    scoring_service: ScoringService,
    max_items: int = SMART_SAMPLING_MAX_ITEMS,
) -> list[ScoredItem]:
    """Sample items for profile building with quota-based selection.

    Strategy:
    1. Always include all loved/liked/added items (strong signals)
    2. Fill remaining slots with top watched items by score
    3. Limit total to prevent excessive API calls
    """
    typed_items = [it for it in library_items.all_items() if it.get("type") == content_type]

    if not typed_items:
        return []

    if len(typed_items) <= max_items:
        return [scoring_service.process_item(it) for it in typed_items]

    # De-duplicate by ID
    unique_items: dict[str, dict] = {}
    for it in typed_items:
        item_id = it.get("_id")
        if item_id:
            unique_items[item_id] = it

    if len(unique_items) <= max_items:
        return [scoring_service.process_item(it) for it in unique_items.values()]

    added_item_ids = {it.get("_id") for it in library_items.added}

    # Separate into pools and score
    loved_liked_pool: list[ScoredItem] = []
    added_pool: list[ScoredItem] = []
    watched_pool: list[ScoredItem] = []

    for it in unique_items.values():
        scored = scoring_service.process_item(it)
        if scored.source_type in ["loved", "liked"]:
            loved_liked_pool.append(scored)
        elif it.get("_id") in added_item_ids:
            added_pool.append(scored)
        else:
            watched_pool.append(scored)

    # Fill quotas
    final: list[ScoredItem] = []
    used_ids: set[str] = set()

    loved_quota = int(max_items * 0.40)
    added_quota = int(max_items * 0.20)
    watched_quota = max_items - loved_quota - added_quota

    for pool, quota in [
        (loved_liked_pool, loved_quota),
        (added_pool, added_quota),
        (watched_pool, watched_quota),
    ]:
        for scored in pool[:quota]:
            final.append(scored)
            used_ids.add(scored.item.id)

    # Backfill remaining slots (priority: Loved > Added > Watched)
    remaining = max_items - len(final)
    if remaining > 0:
        for pool in [loved_liked_pool, added_pool, watched_pool]:
            for scored in pool:
                if remaining <= 0:
                    break
                if scored.item.id not in used_ids:
                    final.append(scored)
                    used_ids.add(scored.item.id)
                    remaining -= 1

    return final
