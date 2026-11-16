import asyncio

from app.services.stremio.library import watch_history_to_library_collection
from app.services.trakt import TraktService

WATCHED = {
    "/users/me/watched/movies": [{"movie": {"title": "Film", "ids": {"imdb": "tt0000001"}}, "plays": 2}],
    "/users/me/watched/shows": [{"show": {"title": "Show", "ids": {"imdb": "tt0000002"}}, "plays": 12}],
}


class FakeClient:
    async def get(self, url, params=None, headers=None):
        if (params or {}).get("page", 1) > 1:
            return []
        return WATCHED.get(url, [])


def test_episode_plays_do_not_make_a_show_loved():
    """Regression: a show's plays count every watched episode, so any show with two
    episodes seen passed the unrated rewatch-as-loved proxy."""
    svc = TraktService.__new__(TraktService)
    svc.client = FakeClient()

    library = watch_history_to_library_collection(asyncio.run(svc.get_history("token")))

    assert [i.id for i in library.loved] == ["tt0000001"]
    assert [i.id for i in library.watched] == ["tt0000002"]
