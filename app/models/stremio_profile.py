from pydantic import BaseModel


class StremioProfile(BaseModel):
    id: str
    name: str
    avatar: str | int | None = None
    has_pin: bool = False
    can_manage_addons: bool = False
    is_master: bool = False
    selected: bool = False
