import copy
import re

# Tokens are either legacy Stremio user ids (~24 char alphanumeric) or minted
# base64url strings (token_urlsafe, includes '-' and '_'). Accept up to 64 chars of
# that alphabet as a sanity check; anything else is malformed.
TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

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

# The secrets the configure page shows in an input, and so the ones a user may
# need to identify. The OAuth tokens are excluded: they surface as "Connected",
# never as an editable value.
_HINTABLE_SECRET_FIELDS = ("tmdb_api_key", "simkl_api_key", "gemini_api_key")

# Enough to recognise which key is on file, far too little to use it — the same
# convention as Stripe, AWS and GitHub key listings.
_HINT_VISIBLE_CHARS = 4


def secret_hints(settings_dict: dict) -> dict[str, str]:
    """Last few characters of each stored key, so the UI can identify it.

    mask_stored_secrets means the page never receives the keys themselves, but a
    user still needs to tell whether the key on file is the one they intended.
    Must be called with plaintext settings, before masking.
    """
    hints: dict[str, str] = {}

    def add(name: str, value: object) -> None:
        if isinstance(value, str) and len(value) > _HINT_VISIBLE_CHARS:
            hints[name] = value[-_HINT_VISIBLE_CHARS:]

    for field in _HINTABLE_SECRET_FIELDS:
        add(field, settings_dict.get(field))

    for field in _SECRET_NESTED_FIELDS:
        block = settings_dict.get(field)
        if isinstance(block, dict):
            add(f"{field}.api_key", block.get("api_key"))

    return hints


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
