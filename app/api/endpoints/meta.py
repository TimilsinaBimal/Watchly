import asyncio

from fastapi import APIRouter, HTTPException, Query
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


@router.get("/api/meta/images")
async def get_meta_images(
    imdb_id: str | None = Query(None, description="IMDb ID (e.g. tt1234567)"),
    tmdb_id: int | None = Query(None, description="TMDB ID (use with kind)"),
    kind: str = Query("movie", description="Type: movie or series"),
    language: str = Query("en-US", description="Language for image preference (e.g. en-US, fr-FR)"),
):
    """
    Return logo, poster and background in the requested language.
    Provide either imdb_id (and optionally kind) or tmdb_id + kind.
    """
    try:
        tmdb = get_tmdb_service(language=language)
        media_type = "tv" if kind == "series" else "movie"

        if imdb_id:
            clean_imdb = imdb_id.strip().lower()
            if not clean_imdb.startswith("tt"):
                clean_imdb = "tt" + clean_imdb
            tid, found_type = await tmdb.find_by_imdb_id(clean_imdb)
            if tid is None:
                raise HTTPException(status_code=404, detail="Title not found on TMDB")
            media_type = found_type
            tmdb_id = tid
        elif tmdb_id is None:
            raise HTTPException(status_code=400, detail="Provide imdb_id or tmdb_id")

        images = await tmdb.get_images_for_title(media_type, tmdb_id, language=language)
        return images
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch meta images: {e}")
        raise HTTPException(status_code=502, detail="Failed to fetch images from TMDB")
