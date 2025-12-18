from urllib.parse import unquote


def parse_identifier(identifier: str) -> tuple[str | None, int | None]:
    """Parse Stremio identifier to extract IMDB ID and TMDB ID.

    Returns (imdb_id, tmdb_id)
    """
    if not identifier:
        return None, None

    decoded = unquote(identifier)
    imdb_id: str | None = None
    tmdb_id: int | None = None

    for token in decoded.split(","):
        token = token.strip()
        if not token:
            continue
        if token.startswith("tt") and imdb_id is None:
            imdb_id = token
        elif token.startswith("tmdb:") and tmdb_id is None:
            try:
                tmdb_id = int(token.split(":", 1)[1])
            except (ValueError, IndexError):
                continue
        if imdb_id and tmdb_id is not None:
            break

    return imdb_id, tmdb_id
