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
