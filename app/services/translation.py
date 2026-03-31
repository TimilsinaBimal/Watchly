import asyncio
import re

from async_lru import alru_cache
from deep_translator import GoogleTranslator
from loguru import logger

# Pre-defined translations for known static catalog names.
# Ensures consistent informal (du-form) German regardless of Google Translate output.
_STATIC_TRANSLATIONS: dict[tuple[str, str], str] = {
    ("de", "Top Picks for You"): "Top Picks für dich",
    ("de", "From your favourite Creators"): "Von deinen Lieblingsschöpfern",
    ("de", "Based on what you loved"): "Basierend auf dem, was du geliebt hast",
    ("de", "Based on what you liked"): "Basierend auf dem, was du gemocht hast",
}


def _normalize_german_formality(text: str) -> str:
    """Normalize German text to use the informal (du) address form consistently."""
    text = re.sub(r"\bWeil Sie\b", "Weil du", text)
    text = re.sub(r"\bwas Sie\b", "was du", text)
    text = re.sub(r"\bfür Sie\b", "für dich", text)
    text = re.sub(r"\bIhren\b", "deinen", text)
    text = re.sub(r"\bIhrem\b", "deinem", text)
    text = re.sub(r"\bIhrer\b", "deiner", text)
    text = re.sub(r"\bIhres\b", "deines", text)
    text = re.sub(r"\bIhre\b", "deine", text)
    if text.endswith(" haben"):
        text = text[:-6] + " hast"
    return text


class TranslationService:
    @alru_cache(maxsize=1000, ttl=7 * 24 * 60 * 60)
    async def translate(self, text: str, target_lang: str | None) -> str:
        if not text or not target_lang:
            return text

        # Normalize lang (e.g. en-US -> en)
        lang = target_lang.split("-")[0].lower()
        if lang == "en":
            return text

        static_key = (lang, text)
        if static_key in _STATIC_TRANSLATIONS:
            return _STATIC_TRANSLATIONS[static_key]

        try:
            loop = asyncio.get_running_loop()

            translated = await loop.run_in_executor(
                None, lambda: GoogleTranslator(source="auto", target=lang).translate(text)
            )
            result = translated if translated else text
            if lang == "de":
                result = _normalize_german_formality(result)
            return result
        except Exception as e:
            logger.exception(f"Translation failed for '{text}' to '{lang}': {e}")
            return text


translation_service = TranslationService()


async def apply_catalog_translation(cat: dict, target_lang: str | None) -> None:
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
