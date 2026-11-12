"""Settings for the agent orchestrator.

Only the three OpenAI-compatible settings the agents need. The other variables
in .env (Supabase, SEED_TOKEN, ...) are ignored, so the tool runs without them.
Point OPENAI_BASE_URL at Gemini's OpenAI-compatible endpoint to use the free tier.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict

# Used when OPENAI_BASE_URL is unset or empty (same fallback as the RAG app).
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"

# A whole page is generated in one call, so allow longer than the app's 30 seconds.
TIMEOUT_SECONDS = 120.0
MAX_RETRIES = 1


class OrchestratorSettings(BaseSettings):
    """OPENAI_API_KEY, OPENAI_BASE_URL and OPENAI_CHAT_MODEL, from the environment or .env."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    openai_api_key: str = ""
    openai_base_url: str = ""
    openai_chat_model: str = "gpt-4o"

    @property
    def base_url(self) -> str:
        """The endpoint to call: OPENAI_BASE_URL, or OpenAI's when that is empty."""
        return self.openai_base_url or DEFAULT_OPENAI_BASE_URL
