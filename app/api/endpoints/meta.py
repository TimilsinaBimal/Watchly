import asyncio

from fastapi import APIRouter, HTTPException
from loguru import logger

from app.services.tmdb.service import get_tmdb_service

router = APIRouter()


async def fetch_languages_list():
    """
    Fetch and format languages list from TMDB.
    Returns a list of language dictionaries with iso_639_1, language, and country.
    """
    tmdb = get_tmdb_service()
    tasks = [
        tmdb.get_primary_translations(),
        tmdb.get_languages(),
        tmdb.get_countries(),
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


@router.get("/api/languages")
async def get_languages():
    try:
        languages = await fetch_languages_list()
        return languages
    except Exception as e:
        logger.error(f"Failed to fetch languages: {e}")
        raise HTTPException(status_code=502, detail="Failed to fetch languages from TMDB")
