import asyncio

from google import genai
from loguru import logger

from app.core.config import settings


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

    def generate_content(self, prompt: str) -> str:
        system_prompt = self.get_prompt()
        if not self.client:
            logger.warning("Gemini client not initialized. Gemini features will be disabled.")
            return ""
        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=system_prompt + "\n\n" + prompt,
            )
            return response.text.strip()
        except Exception as e:
            logger.exception(f"Error generating content with Gemini: {e}")
            return ""

    async def generate_content_async(self, prompt: str) -> str:
        """Async wrapper to avoid blocking the event loop during network calls."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: self.generate_content(prompt))


gemini_service = GeminiService()
