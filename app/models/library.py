from typing import Any

from pydantic import BaseModel


class LibraryCollection(BaseModel):
    """Typed container for categorized library items.

    This is the single shape that flows through the app. When Trakt/Simkl
    history providers are added, they produce the same LibraryCollection
    so the rest of the app doesn't care about the source.
    """

    loved: list[dict[str, Any]] = []
    liked: list[dict[str, Any]] = []
    watched: list[dict[str, Any]] = []
    added: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []

    def all_items(self) -> list[dict[str, Any]]:
        return self.loved + self.liked + self.watched + self.added

    def all_items_with_removed(self) -> list[dict[str, Any]]:
        return self.loved + self.liked + self.watched + self.added + self.removed

    def for_type(self, content_type: str) -> "LibraryCollection":
        return LibraryCollection(
            loved=[i for i in self.loved if i.get("type") == content_type],
            liked=[i for i in self.liked if i.get("type") == content_type],
            watched=[i for i in self.watched if i.get("type") == content_type],
            added=[i for i in self.added if i.get("type") == content_type],
            removed=[i for i in self.removed if i.get("type") == content_type],
        )

    def all_imdb_ids(self) -> set[str]:
        return {i.get("_id", "") for i in self.all_items_with_removed() if i.get("_id", "").startswith("tt")}

    def is_empty(self) -> bool:
        return not any([self.loved, self.liked, self.watched, self.added])
