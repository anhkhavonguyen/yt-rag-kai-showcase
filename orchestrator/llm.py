"""The model client: the only code that talks to the model.

Both agents share one client. They differ only in the prompt they send, so the
same model acts as the builder in one call and as the reviewer in the next.
"""

from typing import Protocol

import httpx
import openai

from .config import MAX_RETRIES, TIMEOUT_SECONDS, OrchestratorSettings


class ModelCallError(Exception):
    """A model call failed, timed out or returned no usable text.

    Holds only the error type and HTTP status, never the provider's message,
    which can echo the API key or account details.
    """

    def __init__(self, error_type: str):
        super().__init__(error_type)
        self.error_type = error_type
        # Set by the agent that made the call, so the output can say who failed.
        self.agent: str | None = None


class ModelClient(Protocol):
    """Anything that can answer one prompt. Tests use a scripted fake."""

    def complete(self, system: str, user: str) -> str:
        """Send a system prompt and a user message; return the reply text."""
        ...


class OpenAICompatibleClient:
    """Calls an OpenAI-compatible chat endpoint, such as Gemini's."""

    def __init__(self, settings: OrchestratorSettings, http_client: httpx.Client | None = None):
        self.model = settings.openai_chat_model
        self.sdk = openai.OpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.base_url,
            timeout=TIMEOUT_SECONDS,
            max_retries=MAX_RETRIES,
            http_client=http_client,  # tests pass an in-memory transport
        )

    def complete(self, system: str, user: str) -> str:
        try:
            response = self.sdk.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
            text = response.choices[0].message.content or ""
        except Exception as e:
            # Keep the error type and HTTP status only; drop the provider's message.
            status = getattr(e, "status_code", None)
            suffix = f" (HTTP {status})" if status else ""
            raise ModelCallError(f"{type(e).__name__}{suffix}") from None
        if not text.strip():
            raise ModelCallError("EmptyReply")
        return text
