from pydantic import BaseModel, Field


class AIOManagerValidateInput(BaseModel):
    instance_url: str = Field(description="AIOManager instance URL, as the user opens it")
    api_key: str | None = Field(
        default=None,
        description="Account API key; omit (or send the stored mark) to check the key already saved",
    )
    token: str | None = Field(
        default=None,
        description="Account token, needed only when api_key is the stored mark so the saved key can be read",
    )


class AIOManagerValidationResponse(BaseModel):
    valid: bool
    message: str


class AIOManagerSyncResponse(BaseModel):
    status: str
    addon_count: int = Field(description="Addons the manager holds for this account after the push")
    instance: str = Field(description="Host of the manager instance the addon was pushed to")
