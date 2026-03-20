import asyncio

from app.services.tmdb.service import TMDBService, get_tmdb_service


async def fetch_languages_list() -> list[dict[str, str]]:
    tmdb_service: TMDBService = get_tmdb_service()
    tasks = [
        tmdb_service.get_primary_translations(),
        tmdb_service.get_languages(),
        tmdb_service.get_countries(),
    ]
    primary_translations, languages, countries = await asyncio.gather(*tasks)

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
