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
