from pydantic import BaseModel


class UserSettings(BaseModel):
    pass


class Credentials(BaseModel):
    authKey: str
    email: str
    user_settings: UserSettings
