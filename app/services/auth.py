import time
from datetime import datetime, timezone
from typing import TypeVar

from fastapi import HTTPException
from loguru import logger

from app.api.models.tokens import TokenRequest, TokenResponse, TraktTokens
from app.core.config import settings
from app.core.security import STORED_SECRET_SENTINEL, mask_stored_secrets, redact_token, secret_hints
from app.core.settings import LLMConfig, PosterRatingConfig, UserSettings, get_default_settings
from app.services.simkl import simkl_service
from app.services.stremio.service import StremioBundle
from app.services.token_store import token_store
from app.services.trakt import trakt_service

KeyedConfigT = TypeVar("KeyedConfigT", LLMConfig, PosterRatingConfig)


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
            raise HTTPException(status_code=400, detail="Failed to verify Stremio identity.")
        finally:
            await bundle.close()

    async def resolve_identities(
        self, payload: TokenRequest, refresh_expired: bool = False
    ) -> tuple[dict[str, str], str | None, str | None]:
        """Verify every credential in the payload with its provider.

        Returns ({provider: provider_user_id}, stremio_auth_key, stremio_email).
        Identities must be derived server-side from the presented credentials —
        trusting client-supplied IDs would let anyone claim another user's account.

        A provider that won't confirm its credential is left out rather than
        failing the whole call: the configure page replays every token it has
        stored, so one stale token (or one provider being down) must not block a
        save the user's other credentials can carry. `create_user_token` still
        rejects the request when the watch history source is the provider that
        failed. `refresh_expired` is only set by callers that store the result —
        Trakt rotates refresh tokens, so spending one without persisting the new
        pair would leave the account unable to refresh again.
        """
        identities: dict[str, str] = {}
        stremio_auth_key: str | None = None
        email: str | None = None

        if payload.authKey or (payload.email and payload.password):
            user_id, email, stremio_auth_key = await self.get_stremio_user_data(payload)
            identities["stremio"] = user_id

        if payload.trakt_access_token and payload.trakt_access_token != STORED_SECRET_SENTINEL:
            if slug := await self._verify_trakt_identity(payload, refresh_expired):
                identities["trakt"] = slug

        if payload.simkl_access_token and payload.simkl_access_token != STORED_SECRET_SENTINEL:
            if account_id := await self._verify_simkl_identity(payload.simkl_access_token):
                identities["simkl"] = account_id

        if not identities:
            raise HTTPException(
                status_code=400,
                detail="Could not verify any connected account. Reconnect Stremio, Trakt, or Simkl and try again.",
            )

        return identities, stremio_auth_key, email

    async def _verify_trakt_identity(self, payload: TokenRequest, refresh_expired: bool) -> str | None:
        """Trakt user id for the payload's token, or None if Trakt won't confirm it."""
        if slug := await self._fetch_trakt_slug(payload.trakt_access_token):
            return slug

        # A returning user's stored access token is regularly past Trakt's ~90
        # day expiry, so retry once behind a refresh before giving up.
        if not refresh_expired or not payload.trakt_refresh_token:
            return None
        if not await self._refresh_trakt_into_payload(payload):
            return None
        return await self._fetch_trakt_slug(payload.trakt_access_token)

    async def _fetch_trakt_slug(self, access_token: str | None) -> str | None:
        if not access_token:
            return None
        try:
            info = await trakt_service.get_user_info(access_token)
        except Exception as e:
            logger.info(f"Trakt identity lookup failed: {e}")
            return None

        user = info.get("user", info) if isinstance(info, dict) else {}
        # The slug is Trakt's stable-ish user id; it only changes if the user
        # renames their Trakt account.
        slug = (user.get("ids") or {}).get("slug")
        return str(slug) if slug else None

    async def _refresh_trakt_into_payload(self, payload: TokenRequest) -> bool:
        """Exchange the payload's Trakt refresh token for a fresh pair.

        The new tokens are written back onto the payload: there is no account
        token to persist against this early, and `_build_user_settings` reads
        them straight off the payload a few steps later.
        """
        redirect_uri = f"{settings.HOST_NAME}/auth/trakt/callback"
        try:
            data = await trakt_service.refresh_token(payload.trakt_refresh_token, redirect_uri)
        except Exception as e:
            logger.warning(f"Trakt token refresh during identity verification failed: {e}")
            return False

        access_token = data.get("access_token")
        if not access_token:
            logger.warning("Trakt refresh returned no access_token during identity verification")
            return False

        expires_in = int(data.get("expires_in") or 0)
        created_at = int(data.get("created_at") or time.time())
        payload.trakt_access_token = access_token
        payload.trakt_refresh_token = data.get("refresh_token") or payload.trakt_refresh_token
        payload.trakt_token_expires_at = created_at + expires_in if expires_in else 0
        logger.info("Refreshed an expired Trakt token while verifying identity")
        return True

    async def _verify_simkl_identity(self, access_token: str) -> str | None:
        """Simkl account id for the token, or None if Simkl won't confirm it."""
        try:
            info = await simkl_service.get_user_settings(access_token, settings.SIMKL_CLIENT_ID)
        except Exception as e:
            logger.info(f"Simkl identity lookup failed: {e}")
            return None

        account_id = (info.get("account") or {}).get("id") if isinstance(info, dict) else None
        return str(account_id) if account_id else None

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
        submitted_trakt_token = payload.trakt_access_token
        identities, stremio_auth_key, resolved_email = await self.resolve_identities(payload, refresh_expired=True)

        # 2. Resolve (and possibly merge) the account these identities belong to
        token, existing_data = await self._resolve_account(identities)

        # 3. Prepare payload. Identities from earlier configurations are kept:
        # a previously linked provider still identifies this account even when
        # this submit doesn't include it.
        stored_identities = dict((existing_data or {}).get("identities") or {})
        stored_identities.update(identities)

        # The source is checked against the linked set, not just this submit: the
        # account was already reached through a verified identity, and the
        # configure page submits a masked token for a provider it can't re-verify.
        if payload.watch_history_source not in stored_identities:
            provider = payload.watch_history_source
            raise HTTPException(
                status_code=400,
                detail=f"Could not verify your {provider.capitalize()} account, "
                f"which is set as your watch history source. Reconnect it and try again.",
            )

        user_settings = self._build_user_settings(payload, (existing_data or {}).get("settings"))
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
            refreshedTrakt=(
                TraktTokens(
                    access_token=payload.trakt_access_token,
                    refresh_token=payload.trakt_refresh_token or "",
                    expires_at=payload.trakt_token_expires_at or 0,
                )
                if payload.trakt_access_token != submitted_trakt_token
                else None
            ),
        )
        return response, stremio_auth_key, user_settings

    def _build_user_settings(self, payload: TokenRequest, stored: dict | None = None) -> UserSettings:
        default_settings = get_default_settings()
        stored = stored or {}

        def unmasked(field: str, value: str | None) -> str | None:
            """A sentinel means the client was never shown this secret — keep the stored one."""
            return stored.get(field) if value == STORED_SECRET_SENTINEL else value

        return UserSettings(
            language=payload.language or default_settings.language,
            catalogs=payload.catalogs if payload.catalogs else default_settings.catalogs,
            poster_rating=self._unmask_nested_key(payload.poster_rating, stored.get("poster_rating")),
            excluded_movie_genres=payload.excluded_movie_genres,
            excluded_series_genres=payload.excluded_series_genres,
            year_min=payload.year_min,
            year_max=payload.year_max,
            popularity=payload.popularity,
            sorting_order=payload.sorting_order,
            simkl_api_key=unmasked("simkl_api_key", payload.simkl_api_key),
            llm=self._unmask_nested_key(payload.llm, self._stored_llm(stored)),
            gemini_api_key=unmasked("gemini_api_key", payload.gemini_api_key),
            tmdb_api_key=unmasked("tmdb_api_key", payload.tmdb_api_key),
            trakt_access_token=unmasked("trakt_access_token", payload.trakt_access_token),
            trakt_refresh_token=unmasked("trakt_refresh_token", payload.trakt_refresh_token),
            trakt_token_expires_at=payload.trakt_token_expires_at,
            simkl_access_token=unmasked("simkl_access_token", payload.simkl_access_token),
            watch_history_source=payload.watch_history_source,
        )

    @staticmethod
    def _stored_llm(stored: dict) -> dict | None:
        """The stored LLM config, including a legacy gemini_api_key seen as one.

        The configure page loads a legacy key into the LLM fields, so it submits
        a masked gemini config that has to resolve against that older field.
        """
        if stored.get("llm"):
            return stored["llm"]
        if stored.get("gemini_api_key"):
            return {"provider": "gemini", "api_key": stored["gemini_api_key"]}
        return None

    @staticmethod
    def _unmask_nested_key(config: KeyedConfigT | None, stored: dict | None) -> KeyedConfigT | None:
        """Restore the stored api_key on an LLM/poster-rating config submitted with a sentinel.

        The stored key only carries over while the provider is unchanged; picking
        a different provider without supplying its key turns the feature off,
        since both models reject a provider with no usable key.
        """
        if config is None or config.api_key != STORED_SECRET_SENTINEL:
            return config

        stored = stored or {}
        if stored.get("provider") != config.provider or not stored.get("api_key"):
            logger.info(f"Masked {config.provider} api_key submitted with no stored key to restore; disabling it")
            return None
        return config.model_copy(update={"api_key": stored["api_key"]})

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
                plain_settings = UserSettings(**raw_settings).model_dump()
            except Exception as e:
                logger.warning(f"Failed to normalize settings for user {user_id}: {e}")
                plain_settings = raw_settings

            # Hints are derived before masking, from the plaintext, so the page can
            # say which key is stored without ever receiving it.
            response["secret_hints"] = secret_hints(plain_settings)
            response["settings"] = mask_stored_secrets(plain_settings)

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
