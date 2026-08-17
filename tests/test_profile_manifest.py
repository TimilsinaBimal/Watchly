from app.core.config import settings
from app.services.manifest import ManifestService


def test_profile_name_is_visible_in_addon_name():
    assert ManifestService._profiled_addon_name("Alice") == f"{settings.ADDON_NAME} - Alice"


def test_profiled_addon_name_is_trimmed_and_stremio_safe_length():
    name = ManifestService._profiled_addon_name("  " + "A" * 100 + "  ")

    assert name.startswith(f"{settings.ADDON_NAME} - ")
    assert len(name) == 64
