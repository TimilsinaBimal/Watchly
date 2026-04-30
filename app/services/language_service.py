import asyncio

from loguru import logger

from app.services.tmdb.service import TMDBService, get_tmdb_service


async def fetch_languages_list() -> list[dict[str, str]]:
    tmdb_service: TMDBService = get_tmdb_service()
    tasks = [
        tmdb_service.get_primary_translations(),
        tmdb_service.get_languages(),
        tmdb_service.get_countries(),
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for label, r in zip(("primary_translations", "languages", "countries"), results):
        if isinstance(r, Exception):
            logger.warning(f"TMDB {label} fetch failed: {r}")
    primary_translations = results[0] if not isinstance(results[0], Exception) else []
    languages = results[1] if not isinstance(results[1], Exception) else []
    countries = results[2] if not isinstance(results[2], Exception) else []

    language_map = {lang["iso_639_1"]: lang["english_name"] for lang in languages}
    country_map = {country["iso_3166_1"]: country["english_name"] for country in countries}

    result = []
    for element in primary_translations:
        # element looks like "en-US"
        parts = element.split("-")
        if len(parts) != 2:
            continue

        lang_code, country_code = parts
        language_name = language_map.get(lang_code)
        country_name = country_map.get(country_code)

        if language_name and country_name:
            result.append(
                {
                    "iso_639_1": element,
                    "language": language_name,
                    "country": country_name,
                }
            )
    result.sort(key=lambda x: (x["iso_639_1"] != "en-US", x["language"]))
    return result
