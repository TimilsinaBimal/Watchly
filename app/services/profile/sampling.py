from app.models.library import LibraryCollection, StremioLibraryItem
from app.models.profile import ScoredItem
from app.services.profile.constants import SMART_SAMPLING_MAX_ITEMS
from app.services.profile.scoring import ScoringService


def sample_items(
    library_items: LibraryCollection,
    content_type: str,
    scoring_service: ScoringService,
    max_items: int = SMART_SAMPLING_MAX_ITEMS,
) -> list[ScoredItem]:
    """Pick the highest-signal items for profile building, capped at max_items.

    At or under the cap every item is used. Above it, items are pooled by signal
    strength (loved/liked, added, watched), each pool sorted by score, and drawn
    against a 40/20/40 quota split, with any leftover slots backfilled
    strongest-first in that same pool order.

    Note the quotas: a user with more loved titles than the loved quota
    contributes only their strongest, not all of them.
    """
    typed_items = [it for it in library_items.all_items() if it.type == content_type]

    if not typed_items:
        return []

    if len(typed_items) <= max_items:
        return [scoring_service.process_item(it) for it in typed_items]

    # De-duplicate by ID
    unique_items: dict[str, StremioLibraryItem] = {}
    for it in typed_items:
        if it.id:
            unique_items[it.id] = it

    if len(unique_items) <= max_items:
        return [scoring_service.process_item(it) for it in unique_items.values()]

    added_item_ids = {it.id for it in library_items.added}

    # Separate into pools and score
    loved_liked_pool: list[ScoredItem] = []
    added_pool: list[ScoredItem] = []
    watched_pool: list[ScoredItem] = []

    for it in unique_items.values():
        scored = scoring_service.process_item(it)
        if scored.source_type in ["loved", "liked"]:
            loved_liked_pool.append(scored)
        elif it.id in added_item_ids:
            added_pool.append(scored)
        else:
            watched_pool.append(scored)

    # Strongest first. The quota slices below take a prefix of each pool, so
    # without this they took whatever order the library happened to arrive in —
    # making a 30-item sample 30 arbitrary items rather than the strongest 30.
    for pool in (loved_liked_pool, added_pool, watched_pool):
        pool.sort(key=lambda scored: scored.score, reverse=True)

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
