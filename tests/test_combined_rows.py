import asyncio

from app.core.settings import UserSettings
from app.services.catalog_definitions import get_catalogs_from_config
from app.services.recommendation.catalog_service import catalog_service


def _settings(sorting_order):
    return UserSettings(
        catalogs=[{"id": "watchly.rec", "enabled": True, "enabled_movie": True, "enabled_series": True}],
        sorting_order=sorting_order,
    )


def test_combined_order_emits_one_all_catalog():
    typed = get_catalogs_from_config(_settings("default"), "watchly.rec", "Top Picks", True, True)
    combined = get_catalogs_from_config(_settings("combined"), "watchly.rec", "Top Picks", True, True)
    assert [c["type"] for c in typed] == ["movie", "series"]
    assert [c["type"] for c in combined] == ["all"]


def test_all_type_interleaves_both_halves_by_rank(monkeypatch):
    rows = {
        "movie": [{"id": "m1", "type": "movie"}, {"id": "m2", "type": "movie"}, {"id": "m3", "type": "movie"}],
        "series": [{"id": "s1", "type": "series"}],
    }
    monkeypatch.setattr(catalog_service, "_validate_inputs", lambda *a: None)
    original = catalog_service.get_catalog

    async def typed_only(token, content_type, catalog_id):
        if content_type == "all":
            return await original(token, content_type, catalog_id)
        return {"metas": rows[content_type]}, {"Cache-Control": "x"}

    monkeypatch.setattr(catalog_service, "get_catalog", typed_only)
    data, headers = asyncio.run(catalog_service.get_catalog("tok", "all", "watchly.rec"))
    assert [m["id"] for m in data["metas"]] == ["m1", "s1", "m2", "m3"]
    assert headers == {"Cache-Control": "x"}
