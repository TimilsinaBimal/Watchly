import base64
import hashlib
import json
import traceback

import httpx
import redis.asyncio as redis
from cryptography.fernet import Fernet
from loguru import logger

from app.core.config import settings
from app.services.token_store import token_store


def decrypt_data(enc_json: str):
    key_bytes = hashlib.sha256(settings.TOKEN_SALT.encode()).digest()
    fernet_key = base64.urlsafe_b64encode(key_bytes)
    cipher = Fernet(fernet_key)
    if not isinstance(enc_json, str):
        return {}
    try:
        decrypted = cipher.decrypt(enc_json.encode()).decode()
    except Exception as exc:
        logger.warning(f"Failed to decrypt data: {exc}")
        raise exc
    return json.loads(decrypted)


async def get_auth_key(username: str, password: str):
    url = "https://api.strem.io/api/login"
    payload = {
        "email": username,
        "password": password,
        "type": "Login",
        "facebook": False,
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        result = await client.post(url, json=payload)
        result.raise_for_status()
        data = result.json()
        auth_key = data.get("result", {}).get("authKey", "")
        return auth_key


async def get_user_info(auth_key):
    url = "https://api.strem.io/api/getUser"
    payload = {
        "type": "GetUser",
        "authKey": auth_key,
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
        result = data.get("result", {})
        email = result.get("email")
        user_id = result.get("_id")
        return email, user_id


async def get_addons(auth_key: str):
    url = "https://api.strem.io/api/addonCollectionGet"
    payload = {
        "type": "AddonCollectionGet",
        "authKey": auth_key,
        "update": True,
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        result = await client.post(url, json=payload)
        result.raise_for_status()
        data = result.json()
        error_payload = data.get("error")
        if not error_payload and (data.get("code") and data.get("message")):
            error_payload = data

        if error_payload:
            message = "Invalid Stremio auth key."
            if isinstance(error_payload, dict):
                message = error_payload.get("message") or message
            elif isinstance(error_payload, str):
                message = error_payload or message
            logger.warning(f"Addon collection request failed: {error_payload}")
            raise ValueError(f"Stremio: {message}")
        addons = data.get("result", {}).get("addons", [])
    logger.info(f"Found {len(addons)} addons")
    return addons


async def update_addon_url(auth_key: str, user_id: str):
    addons = await get_addons(auth_key)
    hostname = settings.HOST_NAME if settings.HOST_NAME.startswith("https") else f"https://{settings.HOST_NAME}"
    for addon in addons:
        if addon.get("manifest", {}).get("id") == settings.ADDON_ID:
            addon["transportUrl"] = f"{hostname}/{user_id}/manifest.json"

    url = "https://api.strem.io/api/addonCollectionSet"
    payload = {
        "type": "AddonCollectionSet",
        "authKey": auth_key,
        "addons": addons,
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        result = await client.post(url, json=payload)
        result.raise_for_status()
        logger.info("Updated addon url")
        return result.json().get("result", {}).get("success", False)


async def decode_old_payloads(encrypted_raw: str):
    key_bytes = hashlib.sha256(settings.TOKEN_SALT.encode()).digest()
    fernet_key = base64.urlsafe_b64encode(key_bytes)
    cipher = Fernet(fernet_key)
    decrypted_json = cipher.decrypt(encrypted_raw.encode()).decode("utf-8")
    payload = json.loads(decrypted_json)
    return payload


def encrypt_auth_key(auth_key: str) -> str:
    # Delegate to TokenStore to keep encryption consistent everywhere
    return token_store.encrypt_token(auth_key)


def prepare_default_payload(email, user_id):
    return {
        "email": email,
        "user_id": user_id,
        "settings": {
            "catalogs": [
                {"id": "watchly.rec", "name": "Recommended", "enabled": True},
                {"id": "watchly.loved", "name": "Because You Loved", "enabled": True},
                {"id": "watchly.watched", "name": "Because You Watched", "enabled": True},
                {"id": "watchly.theme", "name": "Genre & Theme Collections", "enabled": True},
            ],
            "language": "en",
            "rpdb_key": "",
            "excluded_movie_genres": [],
            "excluded_series_genres": [],
        },
    }


async def store_payload(client: redis.Redis, email: str, user_id: str, auth_key: str):
    payload = prepare_default_payload(email, user_id)
    logger.info(f"Storing payload for {user_id}: {payload}")
    try:
        # encrypt auth_key
        if auth_key:
            payload["authKey"] = encrypt_auth_key(auth_key)
        key = f"{settings.REDIS_TOKEN_KEY}{user_id.strip()}"
        await client.set(key, json.dumps(payload))
    except (redis.RedisError, OSError) as exc:
        logger.warning(f"Failed to store payload for {key}: {exc}")


async def process_migration_key(redis_client: redis.Redis, key: str) -> bool:
    try:
        try:
            data_raw = await redis_client.get(key)
        except (redis.RedisError, OSError) as exc:
            logger.warning(f"Failed to fetch payload for {key}: {exc}")
            return False

        if not data_raw:
            logger.warning(f"Failed to fetch payload for {key}: Empty data")
            return False

        try:
            payload = await decode_old_payloads(data_raw)
        except (json.JSONDecodeError, Exception) as exc:
            logger.warning(f"Failed to decode payload for key {key}: {exc}")
            return False

        if payload.get("username") and payload.get("password"):
            auth_key = await get_auth_key(payload["username"], payload["password"])
        elif payload.get("authKey"):
            auth_key = payload.get("authKey")
        else:
            logger.warning(f"Failed to migrate {key}")
            await redis_client.delete(key)
            return False

        email, user_id = await get_user_info(auth_key)
        if not email or not user_id:
            logger.warning(f"Failed to migrate {key}")
            await redis_client.delete(key)
            return False

        new_payload = prepare_default_payload(email, user_id)
        if auth_key:
            new_payload["authKey"] = encrypt_auth_key(auth_key)

        new_key = f"{settings.REDIS_TOKEN_KEY}{user_id.strip()}"
        payload_json = json.dumps(new_payload)

        if settings.TOKEN_TTL_SECONDS and settings.TOKEN_TTL_SECONDS > 0:
            set_success = await redis_client.set(new_key, payload_json, ex=settings.TOKEN_TTL_SECONDS, nx=True)
            if set_success:
                logger.info(
                    f"Stored encrypted credential payload with TTL {settings.TOKEN_TTL_SECONDS} seconds (SETNX)"
                )
        else:
            set_success = await redis_client.setnx(new_key, payload_json)
            if set_success:
                logger.info("Stored encrypted credential payload without expiration (SETNX)")

        if not set_success:
            logger.info(f"Credential payload for {new_key} already exists, not overwriting.")

        await redis_client.delete(key)
        logger.info(f"Migrated {key} to {new_key}")
        return True

    except Exception as exc:
        await redis_client.delete(key)
        traceback.print_exc()
        logger.warning(f"Failed to migrate {key}: {exc}")
        return False


async def migrate_tokens():
    total_tokens = 0
    failed_tokens = 0
    success_tokens = 0
    try:
        redis_client = await token_store._get_client()
    except (redis.RedisError, OSError) as exc:
        logger.warning(f"Failed to connect to Redis: {exc}")
        return

    pattern = f"{settings.REDIS_TOKEN_KEY}*"
    async for key in redis_client.scan_iter(match=pattern):
        total_tokens += 1
        if await process_migration_key(redis_client, key):
            success_tokens += 1
        else:
            failed_tokens += 1

    logger.info(f"[STATS] Total: {total_tokens}, Failed: {failed_tokens}, Success: {success_tokens}")
