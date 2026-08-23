import base64
import zlib

from loguru import logger

# Marks a compressed payload. Values written before compression existed carry no
# prefix and decode as plain JSON, so there is no migration and no double-write.
# Safe as a sentinel because every value this wraps is JSON, which always starts
# with '{' or '['.
_PREFIX = "z1:"

# Below roughly this size zlib's header plus base64's ~33% overhead makes the
# value bigger rather than smaller.
_MIN_COMPRESS_BYTES = 512

# Middle of the range: level 9 costs noticeably more CPU on large libraries for a
# couple of percent less size.
_COMPRESSION_LEVEL = 6


def encode(payload: str) -> str:
    """Compress a cache value, leaving it alone when that wouldn't help.

    base64 rather than raw bytes because the Redis client is built with
    decode_responses=True, so binary values would not round-trip.
    """
    if len(payload) < _MIN_COMPRESS_BYTES:
        return payload

    packed = _PREFIX + base64.b64encode(zlib.compress(payload.encode(), _COMPRESSION_LEVEL)).decode()
    if len(packed) >= len(payload):
        return payload

    logger.debug(f"[CACHE] Compressed {len(payload)}B to {len(packed)}B ({len(packed) / len(payload):.0%})")
    return packed


def decode(raw: str) -> str:
    """Inverse of encode. Unreadable payloads come back as-is.

    Returning the raw value on failure lets the caller's existing JSON parsing
    treat it as a cache miss, instead of every call site having to grow a handler
    for zlib and base64 errors.
    """
    if not raw.startswith(_PREFIX):
        return raw

    try:
        return zlib.decompress(base64.b64decode(raw.removeprefix(_PREFIX))).decode()
    except Exception as e:
        logger.warning(f"[CACHE] Failed to decompress a cached value, treating as a miss: {e}")
        return raw
