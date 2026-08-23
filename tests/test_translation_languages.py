import asyncio

import pytest

from app.services.translation import TranslationService, _google_lang, translation_service


@pytest.fixture
def no_network(monkeypatch):
    """Record what language code reaches Google, without calling it."""
    seen: list[tuple[str, str]] = []

    async def fake_translate(self, text, lang):
        seen.append((text, lang))
        return f"{text}-in-{lang}"

    monkeypatch.setattr(TranslationService, "_translate_cached", fake_translate)
    return seen


def translate(text: str, lang: str | None) -> str:
    return asyncio.run(translation_service.translate(text, lang))


def test_hebrew_reaches_google_as_its_legacy_code(no_network):
    """#157: TMDB gives us 'he', Google only accepts 'iw', and the mismatch made
    every catalog name fall back to English."""
    assert translate("Top Picks for You", "he") == "Top Picks for You-in-iw"
    assert no_network == [("Top Picks for You", "iw")]


def test_other_legacy_code_mismatches_are_mapped(no_network):
    for iso, google in (("jv", "jw"), ("nb", "no"), ("fil", "tl"), ("zh", "zh-CN")):
        no_network.clear()
        translate("Because you loved", iso)
        assert no_network == [("Because you loved", google)], f"{iso} should reach Google as {google}"


def test_regional_tags_are_narrowed_before_mapping(no_network):
    """Stremio sends full tags like he-IL; the region is dropped, then mapped."""
    translate("Top Picks for You", "he-IL")
    assert no_network == [("Top Picks for You", "iw")]


def test_unsupported_language_keeps_the_source_text(no_network):
    assert translate("Top Picks for You", "xx") == "Top Picks for You"
    assert no_network == []  # short-circuited, so no per-catalog exception either


def test_english_and_empty_inputs_short_circuit(no_network):
    assert translate("Top Picks for You", "en-US") == "Top Picks for You"
    assert translate("", "de") == ""
    assert translate("Top Picks for You", None) == "Top Picks for You"
    assert no_network == []


def test_static_translations_still_win(no_network):
    """Curated strings are keyed on the ISO code, so mapping must not bypass them."""
    assert translate("Top Picks for You", "de") == "Top Picks für dich"
    assert no_network == []


def test_supported_codes_pass_through_unchanged(no_network):
    # Not a curated string, so it actually reaches the translator.
    translate("Korean Action Thrillers", "fr")
    assert no_network == [("Korean Action Thrillers", "fr")]


def test_google_lang_resolves_directly():
    assert _google_lang("he") == "iw"
    assert _google_lang("fr") == "fr"
    assert _google_lang("xx") is None
