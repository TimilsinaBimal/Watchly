from loguru import logger

from app.models.stremio_profile import StremioProfile
from app.services.stremio.client import StremioClient


class StremioAuthService:
    """
    Handles authentication and user information retrieval from Stremio.
    """

    def __init__(self, client: StremioClient):
        self.client = client

    async def get_user(self, auth_key: str) -> dict:
        payload = {
            "type": "GetUser",
            "authKey": auth_key,
        }
        data = await self.client.post("/api/getUser", json=payload)

        if "error" in data:
            error_msg = data["error"]
            if isinstance(error_msg, dict):
                error_msg = error_msg.get("message", "Unknown error")
            raise ValueError(f"Stremio API Error: {error_msg}")

        return data.get("result", {})

    async def login(self, email: str, password: str) -> str:
        """
        Authenticate with Stremio using email and password.
        Returns the authKey.
        """
        payload = {
            "email": email,
            "password": password,
            "type": "Login",
            "facebook": False,
        }

        try:
            data = await self.client.post("/api/login", json=payload)
            auth_key = data.get("result", {}).get("authKey")

            if not auth_key:
                error_obj = data.get("error") or data
                error_message = "Invalid Stremio credentials"
                if isinstance(error_obj, dict):
                    error_message = error_obj.get("message") or error_message
                raise ValueError(f"Stremio Auth Error: {error_message}")

            return auth_key
        except Exception as e:
            logger.exception(f"Failed to login to Stremio: {e}")
            raise

    async def get_user_info(self, auth_key: str) -> dict[str, str | None]:
        """
        Fetch user information (ID and Email) using an auth key.
        """
        try:
            result = await self.get_user(auth_key)
            account_id = str(result.get("parent_id") or result.get("_id") or "")
            email = result.get("email")

            if not account_id:
                raise ValueError("User ID missing in Stremio profile response")

            profiles = self._profiles_from_user(result)
            active_profile = next((profile for profile in profiles if profile.selected), None)
            if active_profile is None:
                active_profile = next((profile for profile in profiles if profile.is_master), None)

            is_profile_account = len(profiles) > 1
            profile_id = active_profile.id if active_profile and is_profile_account else None
            profile_name = active_profile.name if active_profile and is_profile_account else None
            user_id = (
                f"{account_id}:{active_profile.id}" if active_profile and not active_profile.is_master else account_id
            )

            return {
                "user_id": user_id,
                "email": email,
                "profile_id": profile_id,
                "profile_name": profile_name,
            }
        except Exception as e:
            logger.exception(f"Failed to fetch Stremio user info: {e}")
            raise

    async def get_profiles(self, auth_key: str) -> list[StremioProfile]:
        user = await self.get_user(auth_key)
        return self._profiles_from_user(user)

    @staticmethod
    def _profiles_from_user(user: dict) -> list[StremioProfile]:
        premium_prefs = user.get("premiumPrefs") or {}
        raw_profiles = premium_prefs.get("userProfiles") or []

        if isinstance(raw_profiles, dict):
            profile_entries = [
                {"_id": profile_id, **profile}
                for profile_id, profile in raw_profiles.items()
                if isinstance(profile, dict)
            ]
        else:
            profile_entries = [profile for profile in raw_profiles if isinstance(profile, dict)]

        master_id = str(user.get("parent_id") or user.get("_id") or "")
        selected_profile_id = premium_prefs.get("selectedProfileId") or premium_prefs.get("selected")
        if not isinstance(selected_profile_id, str):
            selected_profile_id = None
        profiles: list[StremioProfile] = []
        seen: set[str] = set()

        for profile in profile_entries:
            profile_id = str(profile.get("_id") or profile.get("id") or profile.get("profileId") or "")
            if not profile_id or profile_id in seen:
                continue
            seen.add(profile_id)
            profiles.append(
                StremioProfile(
                    id=profile_id,
                    name=profile.get("name") or "Profile",
                    avatar=profile.get("avatar"),
                    has_pin=bool(profile.get("hasPin")),
                    can_manage_addons=bool(profile.get("canManageAddons")),
                    is_master=bool(profile.get("isMaster")) or profile_id == master_id,
                    selected=bool(profile.get("selected")) or profile_id == selected_profile_id,
                )
            )

        if master_id and master_id not in seen:
            profiles.insert(
                0,
                StremioProfile(
                    id=master_id,
                    name=user.get("name") or user.get("email") or "Primary profile",
                    avatar=user.get("avatar"),
                    can_manage_addons=True,
                    is_master=True,
                ),
            )

        if profiles and not any(profile.selected for profile in profiles):
            current_id = str(user.get("_id") or "") if user.get("parent_id") else master_id
            current = next((profile for profile in profiles if profile.id == current_id), None)
            if current is None:
                current = next((profile for profile in profiles if profile.is_master), profiles[0])
            current.selected = True

        return profiles

    async def authenticate_profile(self, auth_key: str, profile_id: str, pin: str | None = None) -> str:
        authenticate_payload = {
            "type": "AuthenticateProfile",
            "authKey": auth_key,
            "profileId": profile_id,
        }
        if pin:
            authenticate_payload["pin"] = pin

        data = await self.client.post("/api/premiumPrefs/authenticateProfile", json=authenticate_payload)
        self._raise_profile_error(data, "authentication")

        profile_auth_key = self._extract_auth_key(data)
        if profile_auth_key:
            return profile_auth_key

        switch_payload = {
            "type": "SetProfile",
            "authKey": auth_key,
            "profileId": profile_id,
        }
        data = await self.client.post("/api/premiumPrefs/setProfile", json=switch_payload)
        self._raise_profile_error(data, "selection")

        profile_auth_key = self._extract_auth_key(data)
        if profile_auth_key:
            return profile_auth_key

        logger.debug(f"Stremio profile selection response shape: {self._response_shape(data)}")
        raise ValueError("Stremio did not return an auth key for the selected profile")

    @staticmethod
    def _extract_auth_key(data) -> str | None:
        result = data.get("result", data)
        if isinstance(result, str):
            return result

        candidates = [result]
        if isinstance(result, dict) and isinstance(result.get("user"), dict):
            candidates.append(result["user"])

        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            profile_auth_key = candidate.get("authKey") or candidate.get("auth_key")
            if profile_auth_key:
                return str(profile_auth_key)

        return None

    @staticmethod
    def _raise_profile_error(data, action: str) -> None:
        if "error" not in data:
            return
        error = data["error"]
        message = error.get("message") if isinstance(error, dict) else str(error)
        raise ValueError(f"Stremio profile {action} failed: {message or 'Unknown error'}")

    @classmethod
    def _response_shape(cls, value, depth: int = 0):
        """Describe an API response without logging credentials or user data."""
        if depth >= 3:
            return type(value).__name__
        if isinstance(value, dict):
            return {key: cls._response_shape(item, depth + 1) for key, item in value.items()}
        if isinstance(value, list):
            return [cls._response_shape(item, depth + 1) for item in value[:1]]
        return type(value).__name__
