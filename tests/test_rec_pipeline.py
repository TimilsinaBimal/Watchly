import asyncio
from datetime import datetime, timedelta, timezone

from app.core.constants import DEFAULT_CATALOG_LIMIT
from app.core.settings import get_default_settings
from app.models.library import LibraryCollection, StremioLibraryItem, StremioState
from app.models.profile import TasteProfile
from app.services.recommendation.catalog_service import catalog_service

DRAMA, HORROR = 18, 27
SEED = 900


class FakeTMDB:
    """Serves only the titles it was given. List endpoints return TMDB's compact shape;
    details for an unknown id fail like a TMDB 404, and discover honours without_genres."""

    def __init__(self, genres_by_id: dict[int, int]):
        self.genres_by_id = {**genres_by_id, SEED: DRAMA}

    def _compact(self, tid: int) -> dict:
        return {
            "id": tid,
            "title": f"tt{tid}",
            "genre_ids": [self.genres_by_id[tid]],
            "vote_average": 8.0,
            "vote_count": 3000,
            "popularity": 100.0,
            "release_date": "2015-01-01",
        }

    def _list(self, exclude: set[int] = frozenset()) -> dict:
        return {"results": [self._compact(t) for t in self.genres_by_id if t != SEED and t not in exclude]}

    async def find_by_imdb_id(self, imdb_id: str):
        tid = int(imdb_id[2:])
        return (tid, "movie") if tid in self.genres_by_id else (None, None)

    async def get_movie_details(self, tmdb_id: int):
        if tmdb_id not in self.genres_by_id:
            raise LookupError(tmdb_id)
        genre = self.genres_by_id[tmdb_id]
        compact = self._compact(tmdb_id)
        del compact["genre_ids"]
        return {**compact, "genres": [{"id": genre, "name": str(genre)}], "external_ids": {"imdb_id": f"tt{tmdb_id}"}}

    async def get_images_for_title(self, media_type: str, tmdb_id: int, language: str):
        return {}

    async def get_recommendations(self, tmdb_id: int, media_type: str, page: int = 1):
        return self._list() if page == 1 else {"results": []}

    async def get_similar(self, tmdb_id: int, media_type: str, page: int = 1):
        return {"results": []}

    async def get_discover(self, media_type: str, page: int = 1, **params):
        if page != 1:
            return {"results": []}
        without = {int(g) for g in params.get("without_genres", "").split("|") if g}
        return self._list(exclude={t for t, g in self.genres_by_id.items() if g in without})

    async def get_trending(self, media_type: str, time_window: str = "week", page: int = 1):
        return self._list()


def item(tid: int, loved: bool = False) -> StremioLibraryItem:
    return StremioLibraryItem(
        _id=f"tt{tid}",
        type="movie",
        name=f"tt{tid}",
        temp=False,
        removed=False,
        _is_loved=loved,
        state=StremioState(
            duration=6000,
            timeWatched=6000,
            timesWatched=1,
            lastWatched=datetime.now(timezone.utc) - timedelta(days=400),
        ),
    )


PROFILE = TasteProfile(genre_scores={DRAMA: 1.0}, director_scores={5: 1.0}, director_frequency={5: 2})

ROUTES = [
    ("watchly.item.tt900", PROFILE),
    ("watchly.theme.a:g18", PROFILE),
    ("watchly.creators", PROFILE),
    ("watchly.rec", PROFILE),
    ("watchly.all.loved", PROFILE),
    ("watchly.rewatch", PROFILE),
    # No profile: the trending fallback.
    ("watchly.rec", None),
]


def row(catalog_id: str, tmdb: FakeTMDB, library: LibraryCollection, profile, settings=None, watched=((), ())):
    watched_tmdb, watched_imdb = watched
    result = asyncio.run(
        catalog_service._get_recommendations(
            catalog_id=catalog_id,
            content_type="movie",
            tmdb_service=tmdb,
            profile=profile,
            watched_tmdb=set(watched_tmdb),
            watched_imdb=set(watched_imdb),
            library_items=library,
            limit=DEFAULT_CATALOG_LIMIT,
            user_settings=settings or get_default_settings(),
        )
    )
    return [m["id"] for m in result]


def test_excluded_genres_are_dropped_on_every_route():
    tmdb = FakeTMDB({1: DRAMA, 2: HORROR})
    settings = get_default_settings()
    settings.excluded_movie_genres = [str(HORROR)]

    for catalog_id, profile in ROUTES:
        library = LibraryCollection(loved=[item(SEED, loved=True)], watched=[item(1), item(2)])
        ids = row(catalog_id, tmdb, library, profile, settings)
        assert "tt1" in ids and "tt2" not in ids, (catalog_id, ids)


def test_watched_titles_are_dropped_except_on_the_rewatch_row():
    tmdb = FakeTMDB({1: DRAMA, 3: DRAMA, 4: DRAMA})
    # 3 is known only by IMDb id, as for a Trakt/Simkl user; 4 only by TMDB id.
    watched = ({4, SEED}, {"tt3", f"tt{SEED}"})

    for catalog_id, profile in ROUTES:
        library = LibraryCollection(loved=[item(SEED, loved=True)], watched=[item(1), item(3), item(4)])
        ids = row(catalog_id, tmdb, library, profile, watched=watched)
        if catalog_id == "watchly.rewatch":
            assert {"tt1", "tt3", "tt4"} <= set(ids), ids
        else:
            assert ids == ["tt1"], (catalog_id, ids)


def test_rows_keep_everything_the_engine_ranked():
    count = DEFAULT_CATALOG_LIMIT + 10
    tmdb = FakeTMDB({t: DRAMA for t in range(1, count + 1)})
    library = LibraryCollection(watched=[item(t) for t in range(1, count + 1)])

    for catalog_id in ("watchly.theme.a:g18", "watchly.rewatch"):
        assert len(row(catalog_id, tmdb, library, PROFILE)) == count, catalog_id
