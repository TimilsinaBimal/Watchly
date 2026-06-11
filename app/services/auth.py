from datetime import datetime, timezone

from fastapi import HTTPException
from loguru import logger

from app.api.models.tokens import TokenRequest, TokenResponse
from app.core.config import settings
from app.core.security import redact_token
from app.core.settings import UserSettings, get_default_settings
from app.services.simkl import simkl_service
from app.services.stremio.service import StremioBundle
from app.services.token_store import token_store
from app.services.trakt import trakt_service


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

    async def store_credentials(self, token: str, payload: dict) -> str:
        """Store credentials, return token."""
        # Ensure last_updated is present if it's a new user
        if "last_updated" not in payload:
            existing = await self.get_credentials(token)
            if existing:
                payload["last_updated"] = existing.get("last_updated")
            else:
                payload["last_updated"] = datetime.now(timezone.utc).isoformat()

        return await token_store.store_user_data(token, payload)

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

    async def resolve_identities(self, payload: TokenRequest) -> tuple[dict[str, str], str | None, str | None]:
        """Verify every credential in the payload with its provider.

        Returns ({provider: provider_user_id}, stremio_auth_key, stremio_email).
        Identities must be derived server-side from the presented credentials —
        trusting client-supplied IDs would let anyone claim another user's account.
        """
        identities: dict[str, str] = {}
        stremio_auth_key: str | None = None
        email: str | None = None

        if payload.authKey or (payload.email and payload.password):
            user_id, email, stremio_auth_key = await self.get_stremio_user_data(payload)
            identities["stremio"] = user_id

        if payload.trakt_access_token:
            identities["trakt"] = await self._verify_trakt_identity(payload.trakt_access_token)

        if payload.simkl_access_token:
            identities["simkl"] = await self._verify_simkl_identity(payload.simkl_access_token)

        if not identities:
            raise HTTPException(
                status_code=400,
                detail="Connect at least one account: Stremio, Trakt, or Simkl.",
            )

        return identities, stremio_auth_key, email

    async def _verify_trakt_identity(self, access_token: str) -> str:
        try:
            info = await trakt_service.get_user_info(access_token)
        except Exception as e:
            logger.error(f"Trakt identity verification failed: {e}")
            raise HTTPException(status_code=400, detail="Failed to verify Trakt account. Reconnect and try again.")

        user = info.get("user", info) if isinstance(info, dict) else {}
        # The slug is Trakt's stable-ish user id; it only changes if the user
        # renames their Trakt account.
        slug = (user.get("ids") or {}).get("slug")
        if not slug:
            raise HTTPException(status_code=400, detail="Trakt did not return a user id. Reconnect and try again.")
        return str(slug)

    async def _verify_simkl_identity(self, access_token: str) -> str:
        try:
            info = await simkl_service.get_user_settings(access_token, settings.SIMKL_CLIENT_ID)
        except Exception as e:
            logger.error(f"Simkl identity verification failed: {e}")
            raise HTTPException(status_code=400, detail="Failed to verify Simkl account. Reconnect and try again.")

        account_id = (info.get("account") or {}).get("id") if isinstance(info, dict) else None
        if not account_id:
            raise HTTPException(status_code=400, detail="Simkl did not return a user id. Reconnect and try again.")
        return str(account_id)

    async def _find_account_token(self, provider: str, provider_user_id: str) -> str | None:
        """Locate the account token for a verified provider identity."""
        token = await token_store.get_token_for_identity(provider, provider_user_id)
        if token and await token_store.get_user_data(token):
            return token
        if provider == "stremio":
            # Accounts created before the identity index used the Stremio user id
            # as their token.
            legacy = await token_store.resolve_alias(provider_user_id)
            if await token_store.get_user_data(legacy):
                return legacy
        return None

    async def _resolve_account(self, identities: dict[str, str]) -> tuple[str, dict | None]:
        """Map verified identities to a single account token.

        When identities span multiple existing accounts (e.g. a Trakt-only
        account and a Stremio account belonging to the same person), the oldest
        account survives and the others are merged into it via token aliases.
        """
        matches: dict[str, dict] = {}
        for provider, provider_user_id in identities.items():
            token = await self._find_account_token(provider, provider_user_id)
            if token and token not in matches:
                data = await token_store.get_user_data(token)
                if data:
                    matches[token] = data

        if not matches:
            return token_store.mint_token(), None

        survivor = min(matches, key=lambda t: matches[t].get("last_updated") or "9999")
        for token in matches:
            if token != survivor:
                logger.info(f"Merging account {redact_token(token)} into {redact_token(survivor)}")
                await token_store.merge_into(token, survivor)
        return survivor, matches[survivor]

    async def create_user_token(self, payload: TokenRequest) -> tuple[TokenResponse, str | None, UserSettings]:
        """
        Main logic for creating or updating a user token.

        Returns:
            Tuple of (TokenResponse, resolved_auth_key, user_settings) so the
            caller can trigger caching without re-fetching credentials.
            resolved_auth_key is None for accounts without Stremio credentials.
        """
        # 1. Verify provided credentials and resolve provider identities
        identities, stremio_auth_key, resolved_email = await self.resolve_identities(payload)

        if payload.watch_history_source not in identities:
            raise HTTPException(
                status_code=400,
                detail=f"Watch history source '{payload.watch_history_source}' requires connecting that account.",
            )

        # 2. Resolve (and possibly merge) the account these identities belong to
        token, existing_data = await self._resolve_account(identities)

        # 3. Prepare payload. Identities from earlier configurations are kept:
        # a previously linked provider still identifies this account even when
        # this submit doesn't include it.
        stored_identities = dict((existing_data or {}).get("identities") or {})
        stored_identities.update(identities)

        user_settings = self._build_user_settings(payload)
        payload_to_store = {
            "email": resolved_email or (existing_data or {}).get("email"),
            "settings": user_settings.model_dump(),
            "identities": stored_identities,
        }
        if "stremio" in identities:
            payload_to_store["user_id"] = identities["stremio"]
            payload_to_store["authKey"] = stremio_auth_key
            if payload.password:
                payload_to_store["password"] = payload.password.strip()
        elif existing_data:
            # Re-configuring through Trakt/Simkl alone must not drop the Stremio
            # credentials already linked to this account.
            for field in ("user_id", "authKey", "password"):
                if existing_data.get(field):
                    payload_to_store[field] = existing_data[field]

        if existing_data:
            payload_to_store["last_updated"] = existing_data.get("last_updated")

        # 4. Store user data and index every identity to this token
        token = await self.store_credentials(token, payload_to_store)
        for provider, provider_user_id in stored_identities.items():
            await token_store.set_identity(provider, provider_user_id, token)

        # If watch_history_source changed (or any other setting that affects
        # the profile), drop cached profiles so the next catalog request
        # rebuilds from the new source instead of serving the stale cache.
        if existing_data:
            try:
                from app.services.user_cache import user_cache as _user_cache

                old_settings = existing_data.get("settings") or {}
                old_source = old_settings.get("watch_history_source", "stremio")
                if old_source != user_settings.watch_history_source:
                    for ct in ("movie", "series"):
                        await _user_cache.invalidate_profile(token, ct)
                        await _user_cache.invalidate_watched_sets(token, ct)
                    await _user_cache.invalidate_all_catalogs(token)
                    logger.info(
                        f"[{redact_token(token)}] watch_history_source changed "
                        f"'{old_source}' -> '{user_settings.watch_history_source}'; cleared profile/catalog caches."
                    )
            except Exception as e:
                logger.warning(f"[{redact_token(token)}] Failed to invalidate caches on source change: {e}")

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
            llm=payload.llm,
            gemini_api_key=payload.gemini_api_key,
            tmdb_api_key=payload.tmdb_api_key,
            trakt_access_token=payload.trakt_access_token,
            trakt_refresh_token=payload.trakt_refresh_token,
            trakt_token_expires_at=payload.trakt_token_expires_at,
            simkl_access_token=payload.simkl_access_token,
            watch_history_source=payload.watch_history_source,
        )

    async def _find_account_for_identities(self, identities: dict[str, str]) -> str | None:
        for provider, provider_user_id in identities.items():
            token = await self._find_account_token(provider, provider_user_id)
            if token:
                return token
        return None

    async def get_identity_with_settings(self, payload: TokenRequest) -> dict:
        """Resolve the account for any verified provider credential and return its settings."""
        identities, _, email = await self.resolve_identities(payload)

        token = await self._find_account_for_identities(identities)
        existing_data = await self.get_credentials(token) if token else None
        exists = bool(existing_data)

        # Keep the Stremio id as user_id when present so existing frontend
        # display logic is unchanged; any verified identity works otherwise.
        user_id = identities.get("stremio") or next(iter(identities.values()))
        response = {"user_id": user_id, "email": email, "exists": exists}

        if exists and existing_data:
            # Token is the user's manifest key; only returned once they've authenticated
            # here, so the dashboard can read their install without a second login.
            response["token"] = token
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
        identities, _, _ = await self.resolve_identities(payload)
        token = await self._find_account_for_identities(identities)

        existing_data = await self.get_credentials(token) if token else None
        if not token or not existing_data:
            raise HTTPException(status_code=404, detail="Account not found.")

        for provider, provider_user_id in (existing_data.get("identities") or {}).items():
            await token_store.delete_identity(provider, provider_user_id)
        await token_store.delete_token(token)
        logger.info(f"[{redact_token(token)}] Account deleted")


auth_service = AuthService()
