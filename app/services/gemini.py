import json

from google import genai
from google.genai import types
from loguru import logger

from app.core.config import settings

FLASH_MODEL = "gemini-2.5-flash"


class GeminiService:
    def __init__(self, model: str = settings.DEFAULT_GEMINI_MODEL):
        self.model = model
        self.client = None
        if api_key := settings.GEMINI_API_KEY:
            try:
                self.client = genai.Client(api_key=api_key)
            except Exception as e:
                logger.warning(f"Failed to initialize Gemini client: {e}")
        else:
            logger.warning("GEMINI_API_KEY not set. Gemini features will be disabled.")

    @staticmethod
    def get_prompt():
        return """
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

    def _get_client(self, api_key: str | None = None) -> genai.Client | None:
        if api_key:
            try:
                return genai.Client(api_key=api_key)
            except Exception as e:
                logger.error(f"Failed to create Gemini client with provided key: {e}")
                return None
        return self.client

    async def generate_content_async(self, prompt: str) -> str:
        if not self.client:
            logger.warning("Gemini client not initialized (no key). Gemini features will be disabled.")
            return ""

        try:
            response = await self.client.aio.models.generate_content(
                model=self.model,
                contents=self.get_prompt() + "\n\n" + prompt,
            )
            return response.text.strip()
        except Exception as e:
            logger.exception(f"Error generating title with Gemini: {e}")
            return ""

    async def generate_flash_content_async(self, prompt: str, system_instruction: str, api_key: str) -> str:
        client = self._get_client(api_key)
        if not client:
            return ""

        try:
            config = types.GenerateContentConfig(
                system_instruction=system_instruction,
            )
            response = await client.aio.models.generate_content(
                model=FLASH_MODEL,
                contents=prompt,
                config=config,
            )
            return response.text.strip()
        except Exception as e:
            logger.exception(f"Error generating content with Gemini Flash: {e}")
            return ""

    async def generate_structured_async(
        self,
        prompt: str,
        response_schema: type | dict,
        system_instruction: str,
        api_key: str,
    ) -> dict | list | None:
        client = self._get_client(api_key)
        if not client:
            return None

        try:
            config = types.GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type="application/json",
                response_schema=response_schema,
            )
            response = await client.aio.models.generate_content(
                model=FLASH_MODEL,
                contents=prompt,
                config=config,
            )
            try:
                return json.loads(response.text)
            except json.JSONDecodeError as e:
                logger.warning(f"Gemini returned non-JSON response: {e}; body={response.text[:200]!r}")
                return None
        except Exception as e:
            logger.exception(f"Error generating structured content with Gemini Flash: {e}")
            return None


gemini_service = GeminiService()
