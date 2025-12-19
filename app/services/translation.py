import asyncio

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
