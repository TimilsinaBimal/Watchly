import asyncio
from typing import Any

from async_lru import alru_cache
from deep_translator import GoogleTranslator
from loguru import logger


class TranslationService:
    @alru_cache(maxsize=1000, ttl=7 * 24 * 60 * 60)
    async def translate(self, text: str, target_lang: str | None) -> str:
        if not text or not target_lang:
            return text

        # Normalize lang (e.g. en-US -> en)
        lang = target_lang.split("-")[0].lower()
        if lang == "en":
            return text

        try:
            loop = asyncio.get_running_loop()

            translated = await loop.run_in_executor(
                None, lambda: GoogleTranslator(source="auto", target=lang).translate(text)
            )
            return translated if translated else text
        except Exception as e:
            logger.exception(f"Translation failed for '{text}' to '{lang}': {e}")
            return text


translation_service = TranslationService()


async def apply_catalog_translation(cat: dict[str, Any], target_lang: str | None) -> None:
    """
    Set catalog display name for the user's language.

    Item-based rows (loved/watched) attach _catalog_name_prefix (UI label) and
    _catalog_name_suffix (work title). Only the prefix is machine-translated so
    titles stay as in the library.
    """
    if "_catalog_name_prefix" in cat and "_catalog_name_suffix" in cat:
        prefix = cat.pop("_catalog_name_prefix")
        suffix = cat.pop("_catalog_name_suffix")
        label = await translation_service.translate(prefix, target_lang) if target_lang else prefix
        cat["name"] = f"{label} {suffix}".strip()
        return

    if cat.get("name") and target_lang:
        try:
            cat["name"] = await translation_service.translate(cat["name"], target_lang)
        except Exception as e:
            logger.warning(f"Failed to translate catalog name '{cat.get('name')}': {e}")
