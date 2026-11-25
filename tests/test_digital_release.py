import asyncio
from datetime import datetime, timezone

from app.core.settings import UserSettings, get_default_settings
from app.services.recommendation.digital_release import (
    digital_release_filter_active,
    filter_movies_without_home_release,
    has_home_release,
    summarize_release_dates,
)

NOW = datetime(2026, 11, 25, tzinfo=timezone.utc)


class FakeTMDB:
    """Serves only the release-date payloads it was given; anything else is empty."""

    def __init__(self, release_dates: dict[int, dict] | None = None, fail_for: set[int] | None = None):
        self.release_dates = release_dates or {}
        self.fail_for = fail_for or set()
        self.calls: list[int] = []

    async def get_release_dates(self, movie_id: int) -> dict:
        self.calls.append(movie_id)
        if movie_id in self.fail_for:
            raise RuntimeError("tmdb down")
        return self.release_dates.get(movie_id, {"id": movie_id, "results": []})


def release_payload(rows: list[list[tuple[int, str]]]) -> dict:
    """rows: one entry per country, each a list of (release type, date) pairs."""
    return {
        "results": [
            {"iso_3166_1": f"C{i}", "release_dates": [{"type": t, "release_date": d} for t, d in row]}
            for i, row in enumerate(rows)
        ]
    }


def movie(tmdb_id: int, **extra) -> dict:
    return {"id": f"tt{tmdb_id}", "type": "movie", "name": f"Movie {tmdb_id}", "_tmdb_id": tmdb_id, **extra}


def run(items, tmdb):
    return asyncio.run(filter_movies_without_home_release(items, tmdb, now=NOW))


def test_summarize_picks_earliest_dates():
    payload = release_payload([[(3, "2026-02-01"), (4, "2026-12-01")], [(3, "2026-01-01"), (6, "2026-11-01")]])

    earliest_any, earliest_home = summarize_release_dates(payload)

    assert earliest_any == datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert earliest_home == datetime(2026, 11, 1, tzinfo=timezone.utc)


def test_has_home_release_decisions():
    past = datetime(2026, 6, 1, tzinfo=timezone.utc)
    future = datetime(2026, 12, 1, tzinfo=timezone.utc)
    old = datetime(2024, 1, 1, tzinfo=timezone.utc)

    assert has_home_release(past, past, NOW)  # home release already happened
    assert not has_home_release(past, future, NOW)  # only cinemas so far, home date announced
    assert not has_home_release(past, None, NOW)  # theatres only, no home date known
    assert not has_home_release(future, None, NOW)  # not released anywhere yet
    assert has_home_release(old, None, NOW)  # long out; assume available
    assert has_home_release(old, future, NOW)  # long out beats a stray future home date
    assert has_home_release(None, None, NOW)  # no data fails open


def test_filter_hides_recent_cinema_only_movies():
    tmdb = FakeTMDB(
        release_dates={
            1: release_payload([[(3, "2026-02-01"), (4, "2026-06-01")]]),  # digital since June
            2: release_payload([[(3, "2026-02-01"), (4, "2026-12-01")]]),  # digital in December
            3: release_payload([[(3, "2026-12-24")]]),  # premiere still ahead
        }
    )

    kept = run([movie(1), movie(2), movie(3)], tmdb)

    assert [m["name"] for m in kept] == ["Movie 1"]
    assert tmdb.calls == [1, 2, 3]


def test_filter_fails_open_on_missing_data_and_errors():
    empty = FakeTMDB()  # TMDB returns no release rows at all
    no_id = FakeTMDB()
    broken = FakeTMDB(fail_for={5})

    assert run([movie(4)], empty) == [movie(4)]
    # Without a TMDB id there is nothing to look up.
    assert run([{"id": "tt9", "type": "movie", "name": "No id"}], no_id) == [
        {"id": "tt9", "type": "movie", "name": "No id"}
    ]
    assert run([movie(5)], broken) == [movie(5)]


def test_old_movies_skip_the_lookup_entirely():
    tmdb = FakeTMDB()

    kept = run([movie(6, releaseInfo="1984"), movie(7, releaseInfo="2025"), movie(8, releaseInfo=None)], tmdb)

    assert kept == [movie(6, releaseInfo="1984"), movie(7, releaseInfo="2025"), movie(8, releaseInfo=None)]
    # Only the 2025 release is recent enough to check ("2025" may still be inside
    # the theatrical window depending on the exact date); None is not a year and
    # goes through the lookup, which finds nothing and keeps the movie.
    assert tmdb.calls == [7, 8]


def test_series_and_order_are_left_alone():
    series = {"id": "tt100", "type": "series", "name": "Show"}
    movies = [movie(1), movie(3)]

    kept = run([series, *movies, movie(2)], FakeTMDB(release_dates={
        1: release_payload([[(3, "2026-02-01"), (4, "2026-06-01")]]),
        2: release_payload([[(3, "2026-02-01"), (4, "2026-06-01")]]),
        3: release_payload([[(3, "2026-02-01"), (4, "2026-12-01")]]),
    }))

    assert [m["name"] for m in kept] == ["Show", "Movie 1", "Movie 2"]


def test_tmdb_id_falls_back_to_the_meta_id():
    tmdb = FakeTMDB(release_dates={12: release_payload([[(3, "2026-12-24")]])})
    odd_id = {"id": "tmdb:12", "type": "movie", "name": "Odd id"}
    kitsu = {"id": "kd123", "type": "movie", "name": "Kitsu"}

    kept = run([odd_id, kitsu], tmdb)

    assert kept == [kitsu]


def test_filter_active_needs_the_setting_a_movie_row_and_a_normal_catalog():
    on = UserSettings(catalogs=[], digital_release_only=True)
    off = get_default_settings()

    assert digital_release_filter_active(on, "movie", "watchly.rec")
    assert not digital_release_filter_active(off, "movie", "watchly.rec")
    assert not digital_release_filter_active(on, "series", "watchly.rec")
    assert not digital_release_filter_active(on, "all", "watchly.rec")
    # Titles the user already watched are the point of the rewatch row.
    assert not digital_release_filter_active(on, "movie", "watchly.rewatch")
    # Per-item row ids are plain catalogs.
    assert digital_release_filter_active(on, "movie", "watchly.item.12345")
    assert digital_release_filter_active(on, "movie", "watchly.theme.2")
