import copy

# Placeholder swapped in for stored secrets before settings are sent to the
# configure page, and swapped back out when that page submits them again.
STORED_SECRET_SENTINEL = "__watchly_stored_secret__"

# Settings fields worth stealing: paid API keys and provider access tokens.
_SECRET_SETTINGS_FIELDS = (
    "tmdb_api_key",
    "simkl_api_key",
    "gemini_api_key",
    "trakt_access_token",
    "trakt_refresh_token",
    "simkl_access_token",
)
_SECRET_NESTED_FIELDS = ("llm", "poster_rating")


def mask_stored_secrets(settings_dict: dict) -> dict:
    """Replace the user's stored secrets with a placeholder they round-trip back.

    The identity lookup is reachable with any single provider credential, so it
    must not hand out the user's other keys — a leaked Trakt token would
    otherwise yield their TMDB and LLM keys too. Masking rather than dropping
    keeps the configure page's semantics: it submits what it was given, an
    emptied field still clears the value, and a typed value still replaces it.
    """
    masked = copy.deepcopy(settings_dict)

    for field in _SECRET_SETTINGS_FIELDS:
        if masked.get(field):
            masked[field] = STORED_SECRET_SENTINEL

    for field in _SECRET_NESTED_FIELDS:
        block = masked.get(field)
        if isinstance(block, dict) and block.get("api_key"):
            block["api_key"] = STORED_SECRET_SENTINEL

    return masked


def redact_token(token: str | None) -> str:
    """
    Redact a token for logging purposes.
    Shows the first 6 characters followed by ***.
    """
    if not token:
        return "None"
    if len(token) <= 6:
        return token
    return f"{token[:6]}***"
