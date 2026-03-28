from loguru import logger

from app.models.profile import TasteProfile
from app.services.gemini import gemini_service
from app.services.profile.constants import GENRE_MAP


class InterestSummaryService:
    def _get_system_prompt(self) -> str:
        return (
            "You are a film analyst and recommender system expert.\n"
            "Your task is to analyze a user's taste profile data and generate an engaging "
            "summary of their viewing preferences.\n\n"
            "The summary should:\n"
            '1. Be written in the second person ("You love...", "Your taste leans towards...").\n'
            "2. Be a short paragraph: 3-5 sentences, so you can capture nuance and variety.\n"
            '3. Capture the main vibe of their interests (e.g., "fast-paced action," '
            '"dark historical dramas," "lighthearted animation").\n'
            "4. Prioritize genres and keywords as the strongest signals of taste.\n"
            "5. Mention specific eras, countries, or runtime preferences when they add color.\n"
            "6. Sound natural, premium, and personalized—like a thoughtful friend describing their taste.\n\n"
            "Do NOT mention specific IDs or raw metrics. Translate the data into a narrative."
        )

    def _format_profile_data(self, profile: TasteProfile) -> str:
        """Format all available profile data into a structured context string.

        Genres and keywords are primary signals; eras, countries, and runtime are context.
        We include more of each so the summary can be richer and longer.
        """
        parts: list[str] = []

        # --- Primary: more genres and keywords for a richer summary ---
        top_genres = profile.get_top_genres(limit=5)
        genre_names = [GENRE_MAP.get(g_id, f"Unknown({g_id})") for g_id, _ in top_genres]
        if genre_names:
            parts.append(f"[Primary] Top Genres (strongest first): {', '.join(genre_names)}")

        top_keywords = profile.get_top_keywords(limit=15)
        if top_keywords:
            keyword_ids = [str(k_id) for k_id, _ in top_keywords]
            parts.append(f"[Primary] Top Keyword IDs (higher = more watched): {', '.join(keyword_ids)}")

        top_countries = [country for country, _ in profile.get_top_countries(limit=2)]
        if top_countries:
            parts.append(f"[Context] Preferred Countries: {', '.join(top_countries)}")

        top_runtimes = sorted(profile.runtime_bucket_scores.items(), key=lambda x: x[1], reverse=True)
        runtime_prefs = [bucket for bucket, _ in top_runtimes[:3]]
        if runtime_prefs:
            parts.append(f"[Context] Runtime Preference: {', '.join(runtime_prefs)}")

        return "\n".join(parts)

    async def generate_summary(
        self,
        profile: TasteProfile,
        api_key: str,
        keyword_names: dict[int, str] | None = None,
    ) -> str:
        """Generate a text summary of the user's interest profile using Gemini.

        Args:
            profile: The user's TasteProfile.
            api_key: Gemini API key (required).
            keyword_names: Optional mapping of keyword ID -> name for richer context.

        Returns:
            Generated summary string, or empty string on failure.
        """
        if not api_key:
            return ""

        try:
            profile_text = self._format_profile_data(profile)
            if not profile_text:
                return ""

            # Enrich with resolved keyword names if available
            if keyword_names:
                top_keywords = profile.get_top_keywords(limit=12)
                resolved = [keyword_names[k_id] for k_id, _ in top_keywords if k_id in keyword_names]
                if resolved:
                    # Replace the keyword IDs line with actual names
                    profile_text = profile_text.replace(
                        next(
                            (line for line in profile_text.split("\n") if "Keyword IDs" in line),
                            "",
                        ),
                        f"[Primary] Top Keywords: {', '.join(resolved)}",
                    )

            prompt = (
                "Based on the following user profile data, write an interest summary (3-5 sentences).\n"
                "Focus primarily on [Primary] signals (genres and keywords); use [Context] to add "
                "flavor. Make it feel personal and specific to this viewer.\n\n"
                f"{profile_text}"
            )

            summary = await gemini_service.generate_flash_content_async(
                prompt=prompt,
                system_instruction=self._get_system_prompt(),
                api_key=api_key,
            )

            return summary
        except Exception as e:
            logger.error(f"Failed to generate interest summary: {e}")
            return ""


interest_summary_service = InterestSummaryService()
