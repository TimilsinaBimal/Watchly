from typing import Any

from loguru import logger
from pydantic_ai import Agent
from pydantic_ai.models import Model
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.providers.openrouter import OpenRouterProvider

from app.core.settings import LLMConfig

TITLE_SYSTEM_PROMPT = """
You are a content catalog naming expert.
Given filters like genre, keywords, countries, or years, generate natural,
engaging catalog row titles that streaming platforms would use.

Examples:
- Genre: Action, Country: South Korea → "Korean Action Thrillers"
- Keyword: "space", Genre: Sci-Fi → "Space Exploration Adventures"
- Genre: Drama, Country: France → "Acclaimed French Cinema"
- Country: "USA" + Genre: "Sci-Fi and Fantasy" → "Hollywood Sci-Fi and Fantasy"
- Keywords: "revenge" + "martial arts" → "Revenge & Martial Arts"

Keep titles:
- Short (2-5 words)
- Natural and engaging
- Focused on what makes the content appealing
- Only return a single best title and nothing else.
"""


def build_model(config: LLMConfig) -> Model:
    model_name = config.resolved_model()
    if config.provider == "gemini":
        return GoogleModel(model_name, provider=GoogleProvider(api_key=config.api_key))
    if config.provider == "openai":
        return OpenAIChatModel(model_name, provider=OpenAIProvider(api_key=config.api_key))
    if config.provider == "anthropic":
        return AnthropicModel(model_name, provider=AnthropicProvider(api_key=config.api_key))
    return OpenAIChatModel(model_name, provider=OpenRouterProvider(api_key=config.api_key))


class LLMService:
    """LLM access for AI features, always on the user's own key.

    No config means the user supplied no key and AI features are off — there is
    deliberately no server-key fallback. Every method degrades to ""/None on
    failure: LLM output is decorative, never load-bearing.
    """

    async def generate_title(self, prompt: str, config: LLMConfig | None) -> str:
        if not config:
            return ""
        try:
            agent = Agent(build_model(config), system_prompt=TITLE_SYSTEM_PROMPT)
            result = await agent.run(prompt)
            return (result.output or "").strip()
        except Exception as e:
            logger.warning(f"LLM title generation failed ({config.provider}): {e}")
            return ""

    async def generate_structured(
        self,
        prompt: str,
        output_type: Any,
        system_instruction: str,
        config: LLMConfig | None,
    ) -> Any | None:
        if not config:
            return None
        try:
            agent = Agent(build_model(config), system_prompt=system_instruction, output_type=output_type)
            result = await agent.run(prompt)
            return result.output
        except Exception as e:
            logger.warning(f"LLM structured generation failed ({config.provider}): {e}")
            return None


llm_service = LLMService()
