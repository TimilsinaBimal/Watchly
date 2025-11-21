"""Utility functions for caching and other helpers."""

import hashlib
import json
from functools import wraps
from typing import Any, Callable, Dict, Optional
from cachetools import TTLCache
from loguru import logger
from fastapi import HTTPException

from app.services.token_store import token_store

# Cache with 1 day TTL (86400 seconds)
CACHE_TTL = 86400

# Create TTL caches for different purposes
_api_cache: TTLCache = TTLCache(maxsize=10000, ttl=CACHE_TTL)
_function_cache: TTLCache = TTLCache(maxsize=1000, ttl=CACHE_TTL)


def _make_cache_key(func_name: str, instance=None, *args, **kwargs) -> str:
    """Create a cache key from function name and arguments."""
    # Convert args and kwargs to a stable string representation
    # For instance methods, include relevant instance attributes
    instance_key = None
    if instance:
        # Include username for StremioService, api_key for TMDBService
        if hasattr(instance, "username"):
            instance_key = instance.username
        elif hasattr(instance, "api_key"):
            instance_key = instance.api_key

    key_data = {
        "func": func_name,
        "instance": instance_key,
        "args": args,
        "kwargs": sorted(kwargs.items()) if kwargs else None,
    }
    key_str = json.dumps(key_data, sort_keys=True, default=str)
    return hashlib.md5(key_str.encode()).hexdigest()


def cached_api_call(func: Callable) -> Callable:
    """Decorator to cache API call results with TTL."""
    func_name = f"{func.__module__}.{func.__qualname__}"

    @wraps(func)
    async def wrapper(*args, **kwargs):
        # For instance methods, args[0] is self
        instance = args[0] if args and hasattr(args[0], "__class__") else None
        cache_key = _make_cache_key(func_name, instance, *args, **kwargs)

        # Check cache
        if cache_key in _api_cache:
            logger.info(f"Cache hit for {func_name}")
            return _api_cache[cache_key]

        # Call function and cache result
        logger.info(f"Cache miss for {func_name}, calling API")
        result = await func(*args, **kwargs)
        _api_cache[cache_key] = result
        return result

    return wrapper


def cached_function(func: Callable) -> Callable:
    """Decorator to cache function results with TTL."""
    func_name = f"{func.__module__}.{func.__qualname__}"

    @wraps(func)
    async def wrapper(*args, **kwargs):
        # For instance methods, args[0] is self
        instance = args[0] if args and hasattr(args[0], "__class__") else None
        cache_key = _make_cache_key(func_name, instance, *args, **kwargs)

        # Check cache
        if cache_key in _function_cache:
            logger.info(f"Cache hit for {func_name}")
            return _function_cache[cache_key]

        # Call function and cache result
        logger.info(f"Cache miss for {func_name}")
        result = await func(*args, **kwargs)
        _function_cache[cache_key] = result
        return result

    return wrapper


def clear_cache():
    """Clear all caches."""
    _api_cache.clear()
    _function_cache.clear()
    logger.info("All caches cleared")


async def resolve_user_credentials(token: str) -> Dict[str, Any]:
    """Resolve credentials from Redis token."""
    if not token:
        raise HTTPException(status_code=400, detail="Missing credentials token. Please reinstall the addon.")

    payload = await token_store.get_payload(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token. Please reconfigure the addon.")

    include_watched = payload.get("includeWatched", False)
    username = payload.get("username")
    password = payload.get("password")
    auth_key = payload.get("authKey")

    if not auth_key and (not username or not password):
        raise HTTPException(status_code=400, detail="Stored token is missing credentials. Please reconfigure the addon.")

    return {
        "username": username,
        "password": password,
        "authKey": auth_key,
        "includeWatched": include_watched,
    }
