import asyncio
from datetime import datetime, timedelta, timezone

from app.core.settings import get_default_settings
from app.models.library import LibraryCollection, StremioLibraryItem, StremioState
from app.models.profile import TasteProfile
from app.services.recommendation.rewatch import RewatchService

DRAMA = 18


class FakeTMDB:
    """Knows only the titles it was given; anything else fails like TMDB does."""

    def __init__(self, titles: dict[str, tuple[int, list[int]]]):
        self.by_imdb = {imdb: tid for imdb, (tid, _) in titles.items()}
        self.details = {
            tid: {
                "id": tid,
                "title": imdb,
                "genres": [{"id": g, "name": str(g)} for g in genres],
                "vote_average": 7.0,
                "vote_count": 500,
                "external_ids": {"imdb_id": imdb},
            }
            for imdb, (tid, genres) in titles.items()
        }

    async def find_by_imdb_id(self, imdb_id: str):
        tid = self.by_imdb.get(imdb_id)
        return (tid, "movie") if tid else (None, None)

    async def get_movie_details(self, tmdb_id: int):
        if tmdb_id not in self.details:
            raise LookupError(tmdb_id)
        return self.details[tmdb_id]


def item(imdb: str, days_ago: int, loved: bool = False) -> StremioLibraryItem:
    return StremioLibraryItem(
        _id=imdb,
        type="movie",
        name=imdb,
        temp=False,
        removed=False,
        _is_loved=loved,
        state=StremioState(
            duration=6000,
            timeWatched=6000,
            timesWatched=1,
            lastWatched=datetime.now(timezone.utc) - timedelta(days=days_ago),
        ),
    )


def picks(library: LibraryCollection, tmdb: FakeTMDB, profile=None) -> list[str]:
    service = RewatchService(tmdb, get_default_settings())
    result = asyncio.run(service.get_rewatch_picks(library, "movie", profile))
    return [m["external_ids"]["imdb_id"] for m in result]


def test_watched_titles_are_served_and_recent_ones_held_back():
    titles = {"tt1": (1, [DRAMA]), "tt2": (2, [DRAMA])}
    library = LibraryCollection(watched=[item("tt1", days_ago=400), item("tt2", days_ago=10)])

    assert picks(library, FakeTMDB(titles)) == ["tt1"]


def test_cooldown_is_ignored_when_everything_is_recent():
    titles = {"tt1": (1, [DRAMA])}
    library = LibraryCollection(watched=[item("tt1", days_ago=10)])

    assert picks(library, FakeTMDB(titles)) == ["tt1"]


def test_unknown_titles_are_dropped():
    titles = {"tt1": (1, [DRAMA])}
    library = LibraryCollection(watched=[item("tt1", 400), item("tt3", 400)])

    assert picks(library, FakeTMDB(titles)) == ["tt1"]


def test_loved_outranks_a_slightly_better_watched_title():
    titles = {"tt1": (1, [DRAMA]), "tt2": (2, [DRAMA])}
    library = LibraryCollection(loved=[item("tt2", 400, loved=True)], watched=[item("tt1", 400)])
    profile = TasteProfile(genre_scores={DRAMA: 1.0})
    tmdb = FakeTMDB(titles)
    # Slightly better rated, so without the boost the watched title wins outright.
    tmdb.details[1]["vote_average"] = 7.5

    assert picks(library, tmdb, profile=profile) == ["tt2", "tt1"]
