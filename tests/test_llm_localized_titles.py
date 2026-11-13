import asyncio

from app.core.settings import LLMConfig
from app.models.profile import TasteProfile
from app.services import llm as llm_module
from app.services.llm import llm_service, title_language_instruction
from app.services.row_generator import LLMRowTheme, RowGeneratorService
from app.services.translation import TranslationService, apply_catalog_translation

CONFIG = LLMConfig(provider="anthropic", api_key="sk-ant-xxx")
PROFILE = TasteProfile(genre_scores={28: 5.0, 53: 3.0, 18: 2.0})


def make_service(monkeypatch):
    service = RowGeneratorService.__new__(RowGeneratorService)  # skip TMDB init

    async def no_keywords(self, ids):
        return {}

    async def no_keyword_id(self, name, profile_kw_map):
        return None

    monkeypatch.setattr(RowGeneratorService, "_resolve_keyword_names", no_keywords)
    monkeypatch.setattr(RowGeneratorService, "_resolve_keyword_to_id", no_keyword_id)
    return service


def test_language_instruction_is_empty_for_english():
    assert title_language_instruction(None) == ""
    assert title_language_instruction("en") == ""
    assert title_language_instruction("en-US") == ""
    assert "it-IT" in title_language_instruction("it-IT")


def test_llm_rows_are_written_in_the_users_language(monkeypatch):
    prompts: list[str] = []

    async def fake_structured(prompt, output_type, system_instruction, config):
        prompts.append(prompt)
        return [LLMRowTheme(title="Misteri di mezzanotte", genres=[28], keywords=["heist"])]

    monkeypatch.setattr("app.services.row_generator.llm_service.generate_structured", fake_structured)
    service = make_service(monkeypatch)

    rows = asyncio.run(service.generate_rows(PROFILE, "movie", llm_config=CONFIG, language="it-IT"))

    assert "it-IT" in prompts[0]
    # Keywords are looked up on TMDB by their English name.
    assert "keywords must stay as English" in prompts[0]
    assert [r.title for r in rows] == ["Misteri di mezzanotte"]
    assert all(r.localized for r in rows)


def test_english_prompt_and_rows_are_unchanged(monkeypatch):
    prompts: list[str] = []

    async def fake_structured(prompt, output_type, system_instruction, config):
        prompts.append(prompt)
        return [LLMRowTheme(title="Midnight Mysteries", genres=[28])]

    monkeypatch.setattr("app.services.row_generator.llm_service.generate_structured", fake_structured)
    service = make_service(monkeypatch)

    rows = asyncio.run(service.generate_rows(PROFILE, "movie", llm_config=CONFIG, language="en-US"))

    assert "BCP-47" not in prompts[0]
    assert not any(r.localized for r in rows)


def test_only_llm_titles_are_marked_localized_on_fallback(monkeypatch):
    """When structured generation fails, template rows get an LLM title; an empty
    LLM answer keeps the English template, which must still be machine-translated."""

    async def no_structured(prompt, output_type, system_instruction, config):
        return None

    answers = iter(["Azione coreana", ""])
    languages: list[str | None] = []

    async def fake_title(prompt, config, language=None):
        languages.append(language)
        return next(answers, "")

    monkeypatch.setattr("app.services.row_generator.llm_service.generate_structured", no_structured)
    monkeypatch.setattr("app.services.row_generator.llm_service.generate_title", fake_title)
    service = make_service(monkeypatch)

    rows = asyncio.run(service.generate_rows(PROFILE, "movie", llm_config=CONFIG, language="it-IT"))

    assert set(languages) == {"it-IT"}
    assert rows[0].title == "Azione coreana" and rows[0].localized
    assert all(not r.localized for r in rows[1:])


def test_generate_title_appends_the_language_instruction(monkeypatch):
    seen: list[str] = []

    class FakeAgent:
        def __init__(self, *args, **kwargs):
            pass

        async def run(self, prompt):
            seen.append(prompt)
            return type("Result", (), {"output": "Titolo"})()

    monkeypatch.setattr(llm_module, "Agent", FakeAgent)
    monkeypatch.setattr(llm_module, "build_model", lambda config: None)

    asyncio.run(llm_service.generate_title("Genre: Action", CONFIG, "it-IT"))
    asyncio.run(llm_service.generate_title("Genre: Action", CONFIG, "en-US"))

    assert "it-IT" in seen[0]
    assert seen[1] == "Genre: Action"


def test_localized_names_skip_machine_translation(monkeypatch):
    sent: list[str] = []

    async def fake_translate(self, text, target_lang):
        sent.append(text)
        return f"{text}-tradotto"

    monkeypatch.setattr(TranslationService, "translate", fake_translate)

    localized = {"name": "Misteri di mezzanotte", "_name_localized": True}
    template = {"name": "Korean Action Thrillers"}
    asyncio.run(apply_catalog_translation(localized, "it-IT"))
    asyncio.run(apply_catalog_translation(template, "it-IT"))

    assert localized == {"name": "Misteri di mezzanotte"}  # flag never reaches the manifest
    assert template["name"] == "Korean Action Thrillers-tradotto"
    assert sent == ["Korean Action Thrillers"]
