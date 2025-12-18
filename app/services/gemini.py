import asyncio

from google import genai
from loguru import logger

from app.core.config import settings


class GeminiService:
    def __init__(self, model: str = settings.DEFAULT_GEMINI_MODEL):
        self.model = model
        self.client = self._init_client()

    def _init_client(self):
        if not settings.GEMINI_API_KEY:
            logger.warning("GEMINI_API_KEY missing. Features disabled.")
            return None
        try:
            return genai.Client(api_key=settings.GEMINI_API_KEY)
        except Exception as e:
            logger.warning(f"Gemini init failed: {e}")
            return None

    def get_system_prompt(self):
        return """
        You are a content catalog naming expert.
        Generate short, engaging streaming catalog titles (2-5 words) given input filters.
        Examples:
        - Genre: Action, Country: South Korea → "Korean Action Thrillers"
        - Keyword: "space", Genre: Sci-Fi → "Space Exploration Adventures"
        Return ONLY the title.
        """

    def generate_content(self, input_text: str) -> str:
        if not self.client:
            return ""
        try:
            # Note: Assuming synchronous client call based on original code usage
            response = self.client.models.generate_content(
                model=self.model,
                contents=f"{self.get_system_prompt()}\n\n{input_text}",
            )
            return response.text.strip()
        except Exception as e:
            logger.error(f"Generate content failed: {e}")
            return ""

    async def generate_content_async(self, prompt: str) -> str:
        if not self.client:
            return ""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: self.generate_content(prompt))


gemini_service = GeminiService()
