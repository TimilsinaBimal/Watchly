import asyncio

from app.core.constants import DEFAULT_CONCURRENCY_LIMIT
from app.services.profile.builder import ProfileBuilder


def test_process_items_bounded_caps_concurrency_and_processes_all():
    """Regression: external (Trakt/Simkl) histories skip sampling and pass every
    item to the builder. The fan-out must stay bounded so a large history doesn't
    overrun TMDB and silently drop items — every item must still be processed."""
    # Skip __init__ (it constructs a real vectorizer/TMDB client); we only need
    # the bounded fan-out, with _process_item replaced by a concurrency tracker.
    builder = ProfileBuilder.__new__(ProfileBuilder)

    state = {"current": 0, "peak": 0}
    processed = []

    async def fake_process_item(item, content_type):
        state["current"] += 1
        state["peak"] = max(state["peak"], state["current"])
        await asyncio.sleep(0.005)
        state["current"] -= 1
        processed.append(item)
        return None

    builder._process_item = fake_process_item

    items = list(range(150))
    results = asyncio.run(builder._process_items_bounded(items, "movie"))

    assert len(results) == 150  # one result slot per item
    assert len(processed) == 150  # every item processed, none dropped
    assert state["peak"] <= DEFAULT_CONCURRENCY_LIMIT  # never exceeded the cap
    assert state["peak"] > 1  # genuinely concurrent, not serialized
