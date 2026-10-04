from datetime import datetime

from app.core.settings import UserSettings, settings_from_credentials
from app.services.recommendation.filtering import build_discover_params, filter_items_by_settings


def test_an_open_ended_year_max_reaches_today():
    params = build_discover_params(UserSettings(catalogs=[], year_min=1990, year_max=None))

    assert params["primary_release_date.lte"] == datetime.now().strftime("%Y-%m-%d")
    assert params["primary_release_date.gte"] == "1990-01-01"


def test_a_fixed_year_max_still_caps():
    params = build_discover_params(UserSettings(catalogs=[], year_max=2020))
    assert params["primary_release_date.lte"] == "2020-12-31"

    items = [{"release_date": "2020-05-01"}, {"release_date": "2021-05-01"}]
    assert filter_items_by_settings(items, UserSettings(catalogs=[], year_max=2020), apply_quality_band=False) == [
        items[0]
    ]


def test_a_year_max_saved_at_the_slider_end_reads_as_open_ended():
    """An account saved in 2026 with year_max 2026 must still see 2027 releases."""
    saved_at_right_end = {"settings": {"catalogs": [], "year_max": 2026}, "last_updated": "2026-10-03T10:00:00+00:00"}
    assert settings_from_credentials(saved_at_right_end).year_max is None

    chosen_cap = {"settings": {"catalogs": [], "year_max": 2020}, "last_updated": "2026-10-03T10:00:00+00:00"}
    assert settings_from_credentials(chosen_cap).year_max == 2020

    # Saved after the slider gained its "now" notch: a current-year pick is deliberate.
    picked_this_year = {"settings": {"catalogs": [], "year_max": 2026}, "last_updated": "2026-10-04T00:00:01+00:00"}
    assert settings_from_credentials(picked_this_year).year_max == 2026


def test_the_slider_right_end_is_one_past_the_current_year():
    from app.core.settings import get_current_year, get_default_year_range

    assert get_default_year_range()["max"] == get_current_year() + 1
