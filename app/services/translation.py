import asyncio
import re
import time
from typing import Any

from async_lru import alru_cache
from deep_translator import GoogleTranslator
from deep_translator.exceptions import TooManyRequests
from loguru import logger

# Pre-defined translations for known static catalog names.
# Ensures consistent informal (du-form) German regardless of Google Translate output.
# French: short UI labels are ambiguous for MT (e.g. "More like" → wrong parsing of "like").
# Italian: avoids literal MT phrasing for short UI labels.
_STATIC_TRANSLATIONS: dict[tuple[str, str], str] = {
    ("de", "Top Picks for You"): "Top Picks für dich",
    ("de", "From your favourite Creators"): "Von deinen Lieblingsschöpfern",
    ("de", "Based on what you loved"): "Basierend auf dem, was du geliebt hast",
    ("de", "Based on what you liked"): "Basierend auf dem, was du gemocht hast",
    ("fr", "Top Picks for You"): "Sélectionnés pour vous",
    ("fr", "More Like"): "Titres similaires à",
    ("fr", "More like"): "Titres similaires à",
    ("fr", "Because you watched"): "Parce que vous avez regardé",
    ("fr", "Because you loved"): "Parce que vous avez adoré",
    ("de", "Because you watched"): "Weil du angesehen hast",
    ("de", "Because you loved"): "Weil du geliebt hast",
    ("fr", "Genre & Keyword Catalogs"): "Genres et mots-clés",
    ("fr", "From your favourite Creators"): "De vos créateurs préférés",
    ("fr", "Based on what you loved"): "D'après vos coups de cœur",
    ("fr", "Based on what you liked"): "D'après ce que vous avez aimé",
    ("it", "Top Picks for You"): "Scelti per te",
    ("it", "Because you watched"): "Perché hai guardato",
    ("it", "Because you loved"): "Perché hai adorato",
    ("it", "More Like"): "Simili a",
    ("it", "More like"): "Simili a",
    ("it", "Genre & Keyword Catalogs"): "Generi e parole chiave",
    ("it", "From your favourite Creators"): "Dai tuoi autori preferiti",
    ("it", "Based on what you loved"): "In base a ciò che hai adorato",
    ("it", "Based on what you liked"): "In base a ciò che ti è piaciuto",
    ("it", "Watch it again"): "Da riguardare",    
}

# Google's translate codes predate ISO 639-1 in a few places, and TMDB hands us the
# ISO form. Without these the language is simply rejected and every catalog name
# silently falls back to English (#157).
_GOOGLE_LANG_OVERRIDES: dict[str, str] = {
    "he": "iw",  # Hebrew
    "jv": "jw",  # Javanese
    "nb": "no",  # Norwegian Bokmal
    "fil": "tl",  # Filipino
    "zh": "zh-CN",  # Chinese; the regional variant is lost when the tag is split
}

# Google allows 5 requests/second from one IP and answers 429 above that. A manifest
# translates 20-30 names concurrently, so uncached calls are spaced out (#195).
_MIN_INTERVAL_SECONDS = 0.25
_RETRY_AFTER_SECONDS = 1.0
# ponytail: per-process pacing; a Redis token bucket if uvicorn ever runs with --workers > 1.
_next_slot = 0.0


async def _wait_for_slot() -> None:
    # No lock needed: the read-modify-write has no await, so it is atomic on the loop.
    global _next_slot
    now = time.monotonic()
    slot = max(_next_slot, now)
    _next_slot = slot + _MIN_INTERVAL_SECONDS
    await asyncio.sleep(slot - now)


# Static dict inside deep-translator, no network call.
_SUPPORTED_GOOGLE_CODES: frozenset[str] = frozenset(GoogleTranslator().get_supported_languages(as_dict=True).values())


def _google_lang(lang: str) -> str | None:
    """Google's code for an ISO language, or None when it cannot translate it.

    Checking up front rather than letting the constructor raise: it raises once per
    catalog, and each one logged a full traceback for a condition that is a property
    of the language, not of the call.
    """
    code = _GOOGLE_LANG_OVERRIDES.get(lang, lang)
    return code if code in _SUPPORTED_GOOGLE_CODES else None


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

        google_lang = _google_lang(lang)
        if google_lang is None:
            logger.debug(f"Google Translate has no code for '{lang}'; keeping the source text")
            return text

        try:
            return await self._translate_cached(text, google_lang)
        except Exception as e:
            # Fall back to source text on failure but don't cache the fallback —
            # otherwise a transient API blip poisons the cache for 7 days.
            logger.warning(f"Translation failed for '{text}' to '{lang}': {type(e).__name__}: {e}")
            return text

    @alru_cache(maxsize=1000, ttl=7 * 24 * 60 * 60)
    async def _translate_cached(self, text: str, lang: str) -> str:
        try:
            translated = await self._call_google(text, lang)
        except TooManyRequests:
            await asyncio.sleep(_RETRY_AFTER_SECONDS)
            translated = await self._call_google(text, lang)
        result = translated if translated else text
        if lang == "de":
            result = _normalize_german_formality(result)
        return result

    @staticmethod
    async def _call_google(text: str, lang: str) -> str:
        await _wait_for_slot()
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: GoogleTranslator(source="auto", target=lang).translate(text))


translation_service = TranslationService()


async def apply_catalog_translation(cat: dict[str, Any], target_lang: str | None) -> None:
    """
    Set catalog display name for the user's language.

    Item-based rows (loved/watched) attach _catalog_name_prefix (UI label) and
    _catalog_name_suffix (work title). Only the prefix is machine-translated so
    titles stay as in the library.

    Rows flagged _name_localized were written by the LLM in the user's language
    already; translating them again would only mangle them.
    """
    if cat.pop("_name_localized", False):
        return

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
