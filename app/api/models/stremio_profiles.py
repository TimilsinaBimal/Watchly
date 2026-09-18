from pydantic import BaseModel, Field

from app.models.stremio_profile import StremioProfile


class StremioCredentialsRequest(BaseModel):
    authKey: str | None = Field(default=None, description="Stremio auth key")
    email: str | None = Field(default=None, description="Stremio account email")
    password: str | None = Field(default=None, description="Stremio account password")


class StremioProfileAuthRequest(StremioCredentialsRequest):
    profile_id: str
    pin: str | None = None


class StremioProfilesResponse(BaseModel):
    profiles: list[StremioProfile]


class StremioProfileAuthResponse(BaseModel):
    authKey: str
    profile_id: str
    profile_name: str


class StremioProfileAddonInstallRequest(BaseModel):
    authKey: str
    profile_id: str
    manifest_url: str


class StremioProfileAddonInstallResponse(BaseModel):
    success: bool


class StremioProfileInstance(BaseModel):
    profile_id: str
    profile_name: str
    token: str | None = None


class StremioProfileInstancesResponse(BaseModel):
    instances: list[StremioProfileInstance]
