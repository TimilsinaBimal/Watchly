from loguru import logger

from app.services.stremio.client import StremioClient


class StremioAuthService:
    """
    Handles authentication and user information retrieval from Stremio.
    """

    def __init__(self, client: StremioClient):
        self.client = client

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

    async def get_user_info(self, auth_key: str) -> dict[str, str]:
        """
        Fetch user information (ID and Email) using an auth key.
        """
        payload = {
            "type": "GetUser",
            "authKey": auth_key,
        }

        try:
            data = await self.client.post("/api/getUser", json=payload)

            if "error" in data:
                error_msg = data["error"]
                if isinstance(error_msg, dict):
                    error_msg = error_msg.get("message", "Unknown error")
                raise ValueError(f"Stremio API Error: {error_msg}")

            result = data.get("result", {})
            user_id = result.get("_id")
            email = result.get("email")

            if not user_id:
                raise ValueError("User ID missing in Stremio profile response")

            return {"user_id": user_id, "email": email}
        except Exception as e:
            logger.exception(f"Failed to fetch Stremio user info: {e}")
            raise
