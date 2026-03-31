from datetime import datetime, timezone

from fastapi import HTTPException
from loguru import logger

from app.api.models.tokens import TokenRequest, TokenResponse
from app.core.config import settings
from app.core.security import redact_token
from app.core.settings import UserSettings, get_default_settings
from app.services.stremio.service import StremioBundle
from app.services.token_store import token_store


class AuthService:
    async def resolve_auth_key(self, credentials: dict, token: str | None = None) -> str | None:
        """Validate auth key. If expired, try email+password login. Update store on refresh."""
        bundle = StremioBundle()
        try:
            return await self.resolve_auth_key_with_bundle(bundle, credentials, token)
        finally:
            await bundle.close()

    async def resolve_auth_key_with_bundle(
        self,
        bundle: StremioBundle,
        credentials: dict,
        token: str | None = None,
    ) -> str | None:
        """Validate auth key with an existing Stremio bundle."""
        auth_key = (credentials.get("authKey") or "").strip() or None
        email = (credentials.get("email") or "").strip() or None
        password = (credentials.get("password") or "").strip() or None

        if auth_key and auth_key.startswith('"') and auth_key.endswith('"'):
            auth_key = auth_key[1:-1].strip()

        # 1. Try existing auth key
        if auth_key:
            try:
                await bundle.auth.get_user_info(auth_key)
                return auth_key
            except Exception:
                logger.info("Stremio auth key expired or invalid, attempting refresh with credentials")

        # 2. Try login if auth key failed or wasn't provided
        if email and password:
            try:
                new_key = await bundle.auth.login(email, password)
                if token and new_key != auth_key:
                    existing_data = await self.get_credentials(token)
                    if existing_data:
                        existing_data["authKey"] = new_key
                        await token_store.update_user_data(token, existing_data)
                return new_key
            except Exception as e:
                logger.error(f"Stremio login failed: {e}")
                return None

        return None

    async def require_auth_key(self, bundle: StremioBundle, credentials: dict, token: str | None = None) -> str:
        """Resolve auth key or raise a user-facing error."""
        auth_key = await self.resolve_auth_key_with_bundle(bundle, credentials, token)
        if not auth_key:
            raise HTTPException(status_code=401, detail="Stremio session expired. Please reconfigure.")
        return auth_key

    async def get_credentials(self, token: str) -> dict | None:
        """Get user credentials from token store."""
        return await token_store.get_user_data(token)

    async def store_credentials(self, user_id: str, payload: dict) -> str:
        """Store credentials, return token."""
        # Ensure last_updated is present if it's a new user
        if "last_updated" not in payload:
            token = token_store.get_token_from_user_id(user_id)
            existing = await self.get_credentials(token)
            if existing:
                payload["last_updated"] = existing.get("last_updated")
            else:
                payload["last_updated"] = datetime.now(timezone.utc).isoformat()

        return await token_store.store_user_data(user_id, payload)

    async def get_stremio_user_data(self, payload: TokenRequest) -> tuple[str, str, str]:
        """
        Authenticates with Stremio and returns (user_id, email, auth_key).
        """
        creds = payload.model_dump()
        auth_key = await self.resolve_auth_key(creds)

        if not auth_key:
            raise HTTPException(
                status_code=400,
                detail="Failed to verify Stremio identity. Provide valid credentials.",
            )

        bundle = StremioBundle()
        try:
            user_info = await bundle.auth.get_user_info(auth_key)
            user_id = user_info["user_id"]
            resolved_email = user_info.get("email", payload.email or "")
            return user_id, resolved_email, auth_key
        except Exception as e:
            logger.error(f"Stremio identity verification failed: {e}")
            raise HTTPException(status_code=400, detail=f"Failed to verify Stremio identity: {e}")
        finally:
            await bundle.close()

    async def create_user_token(self, payload: TokenRequest) -> tuple[TokenResponse, str, UserSettings]:
        """
        Main logic for creating or updating a user token.

        Returns:
            Tuple of (TokenResponse, resolved_auth_key, user_settings) so the
            caller can trigger caching without re-fetching credentials.
        """
        # 1. Authenticate and get user info
        user_id, resolved_email, stremio_auth_key = await self.get_stremio_user_data(payload)

        # 2. Check if user already exists
        token = token_store.get_token_from_user_id(user_id)
        existing_data = await self.get_credentials(token)

        # 3. Prepare payload
        user_settings = self._build_user_settings(payload)
        payload_to_store = {
            "authKey": stremio_auth_key,
            "email": resolved_email,
            "settings": user_settings.model_dump(),
        }
        if payload.password:
            payload_to_store["password"] = payload.password.strip()

        if existing_data:
            payload_to_store["last_updated"] = existing_data.get("last_updated")

        # 4. Store user data
        token = await self.store_credentials(user_id, payload_to_store)

        # 5. Build response
        base_url = settings.HOST_NAME
        manifest_url = f"{base_url}/{token}/manifest.json"
        expires_in = settings.TOKEN_TTL_SECONDS if settings.TOKEN_TTL_SECONDS > 0 else None

        response = TokenResponse(
            token=token,
            manifestUrl=manifest_url,
            expiresInSeconds=expires_in,
        )
        return response, stremio_auth_key, user_settings

    def _build_user_settings(self, payload: TokenRequest) -> UserSettings:
        default_settings = get_default_settings()
        return UserSettings(
            language=payload.language or default_settings.language,
            catalogs=payload.catalogs if payload.catalogs else default_settings.catalogs,
            poster_rating=payload.poster_rating,
            excluded_movie_genres=payload.excluded_movie_genres,
            excluded_series_genres=payload.excluded_series_genres,
            year_min=payload.year_min,
            year_max=payload.year_max,
            popularity=payload.popularity,
            sorting_order=payload.sorting_order,
            simkl_api_key=payload.simkl_api_key,
            gemini_api_key=payload.gemini_api_key,
            tmdb_api_key=payload.tmdb_api_key,
        )

    async def get_identity_with_settings(self, payload: TokenRequest) -> dict:
        """Fetch Stremio identity and associated user settings if they exist."""
        user_id, email, _ = await self.get_stremio_user_data(payload)

        token = token_store.get_token_from_user_id(user_id)
        existing_data = await self.get_credentials(token)
        exists = bool(existing_data)

        response = {"user_id": user_id, "email": email, "exists": exists}

        if exists and existing_data:
            # Reconstruct UserSettings to ensure defaults are included for old accounts
            raw_settings = existing_data.get("settings", {})
            try:
                user_settings = UserSettings(**raw_settings)
                response["settings"] = user_settings.model_dump()
            except Exception as e:
                logger.warning(f"Failed to normalize settings for user {user_id}: {e}")
                response["settings"] = raw_settings

        return response

    async def delete_user_account(self, payload: TokenRequest) -> None:
        """Deletes user account and associated data."""
        user_id, _, _ = await self.get_stremio_user_data(payload)
        token = token_store.get_token_from_user_id(user_id)

        existing_data = await self.get_credentials(token)
        if not existing_data:
            raise HTTPException(status_code=404, detail="Account not found.")

        await token_store.delete_token(token)
        logger.info(f"[{redact_token(token)}] Token deleted for user {user_id}")


auth_service = AuthService()
