class CustomPosterService:
    """User-defined poster URL built from a template with placeholders.

    The server never fetches the result; Stremio's client does. Placeholders:
    {imdb_id}, {api_key} (optional), {language} (e.g. "en-US"), {language_short} (e.g. "en").
    """

    def get_poster_url(
        self,
        url_template: str,
        imdb_id: str | None,
        api_key: str | None,
        language: str | None,
    ) -> str | None:
        # Every template requires an IMDb id; TMDB-only items have none, so we
        # signal "no custom poster" and let the caller keep the TMDB poster.
        if not imdb_id or not url_template:
            return None

        language = language or ""
        return (
            url_template.replace("{imdb_id}", imdb_id)
            .replace("{api_key}", api_key or "")
            .replace("{language_short}", language.split("-")[0])
            .replace("{language}", language)
        )
