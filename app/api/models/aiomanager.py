from pydantic import BaseModel, Field


class AIOManagerValidateInput(BaseModel):
    instance_url: str = Field(description="AIOManager instance URL, as the user opens it")
    api_key: str | None = Field(default=None, description="Account API key to check")


class AIOManagerSyncResponse(BaseModel):
    status: str
    addon_count: int = Field(description="Addons the manager holds for this account after the push")
    instance: str = Field(description="Host of the manager instance the addon was pushed to")
