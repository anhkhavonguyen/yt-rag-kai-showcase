# Copyright 2024
# Directory: yt-rag/app/services/chat.py

"""
Chat completion service for generating RAG responses.
Supports both OpenAI and Anthropic with configurable models.
"""

import logging
from typing import List, Dict, Any
import openai
import anthropic
from ..core import observability
from ..core.config import DEFAULT_OPENAI_BASE_URL, get_settings
from ..data.default_documents import LINKEDIN_URL

logger = logging.getLogger(__name__)
settings = get_settings()

MAX_ANSWER_TOKENS = 1000

# The assistant answers visitors' questions about Kha Vo (Kai) from the profile documents.
SYSTEM_PROMPT = f"""You are the assistant on Kha Vo's profile page. Kha Vo goes by Kai. Visitors such as
recruiters, clients and colleagues ask you about Kai.

Rules:
1. "Kai" and "Kha Vo" are the same person. Talk about Kai in the third person, by name.
2. You are not Kai. Never write as Kai. Never accept offers, agree to meetings, or state
   Kai's availability or rates; suggest contacting Kai on LinkedIn ({LINKEDIN_URL})
   instead.
3. Answer questions about Kai only from the context. Cite every passage you use with its
   [chunk_id].
4. If the context doesn't answer the question, say Kai's profile doesn't cover it and
   suggest contacting Kai on LinkedIn ({LINKEDIN_URL}). Never guess or add facts.
5. If a question isn't about Kai, say briefly that you answer questions about Kai and
   suggest one, such as "What can Kai do?". Don't answer it from general knowledge.
6. Reply to greetings briefly and offer to help.
7. Write plain text without Markdown: no **, # or backticks. For a list, start each item
   on its own line with "- ".
8. Be concise, friendly and professional."""


class ChatUnavailableError(RuntimeError):
    """The chat model couldn't produce an answer.

    Deliberately carries no provider error text, so it can't leak request or
    account details into API responses.
    """


class ChatService:
    """Service for chat completions supporting multiple AI providers."""
    
    def __init__(self):
        """Initialize chat clients based on configuration."""
        self.provider = settings.ai_provider
        
        if self.provider == "openai":
            self.client = openai.OpenAI(
                api_key=settings.openai_api_key,
                base_url=settings.openai_base_url or DEFAULT_OPENAI_BASE_URL,
                timeout=settings.openai_timeout_seconds,
                max_retries=settings.openai_max_retries,
            )
            self.model = settings.openai_chat_model
        elif self.provider == "anthropic":
            self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
            self.model = settings.anthropic_chat_model
        else:
            raise ValueError(f"Unsupported AI provider: {self.provider}")

        self.provider_label = observability.provider_label(settings.openai_base_url, self.provider)
        
        logger.info(f"Initialized chat service with {self.provider} ({self.model})")
    
    async def generate_answer(self, query: str, context_blocks: List[Dict[str, Any]]) -> str:
        """
        Generate RAG answer using context blocks.
        
        Args:
            query: User's question
            context_blocks: Retrieved chunks with metadata
            
        Returns:
            Generated answer with citations

        Raises:
            ChatUnavailableError: the provider call failed or returned no text
        """
        # Build context string with citations
        context_parts = []
        for block in context_blocks:
            chunk_id = block.get('chunk_id', 'unknown')
            text = block.get('text', '')
            context_parts.append(f"[{chunk_id}] {text}")
        
        context = "\n\n".join(context_parts)
        
        user_prompt = f"""Context:
                        {context}

                        Question: {query}

                        Please provide an answer based on the context above, including appropriate citations."""

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        # One LLM span per model request, including a failed one.
        with observability.llm("chat_completion", model=self.model, provider=self.provider_label) as span:
            span.record(
                input=messages,
                metadata={"temperature": settings.temperature, "max_tokens": MAX_ANSWER_TOKENS},
            )
            try:
                if self.provider == "openai":
                    response = self.client.chat.completions.create(
                        model=self.model,
                        messages=messages,
                        temperature=settings.temperature,
                        max_tokens=MAX_ANSWER_TOKENS
                    )
                    answer = response.choices[0].message.content
                    usage = _token_metrics(getattr(response, "usage", None), "prompt_tokens", "completion_tokens")

                elif self.provider == "anthropic":
                    response = self.client.messages.create(
                        model=self.model,
                        max_tokens=MAX_ANSWER_TOKENS,
                        temperature=settings.temperature,
                        system=SYSTEM_PROMPT,
                        messages=[{"role": "user", "content": user_prompt}]
                    )
                    answer = response.content[0].text
                    usage = _token_metrics(getattr(response, "usage", None), "input_tokens", "output_tokens")

            except Exception as e:
                # Log the error type and HTTP status only: provider messages can echo
                # request or account details, and none of it may reach API responses
                # or traces.
                status = observability.http_status_of(e)
                logger.error(
                    "Chat model request failed: %s%s",
                    type(e).__name__,
                    f" (HTTP {status})" if status else "",
                )
                span.fail(type(e).__name__, status)
                raise ChatUnavailableError(f"Chat model request failed ({type(e).__name__})") from None

            span.record(output=[{"role": "assistant", "content": answer or ""}], metrics=usage)
            if not answer or not answer.strip():
                logger.error("Chat model returned an empty answer")
                span.fail("EmptyAnswer")
                raise ChatUnavailableError("Chat model returned an empty answer")

        logger.info(f"Generated answer using {self.provider}")
        return answer


def _token_metrics(usage, input_field: str, output_field: str) -> dict:
    """Token counts from a provider's usage object, as span metrics; {} if not reported."""
    metrics = {}
    input_tokens = getattr(usage, input_field, None)
    output_tokens = getattr(usage, output_field, None)
    if isinstance(input_tokens, int):
        metrics["input_tokens"] = input_tokens
    if isinstance(output_tokens, int):
        metrics["output_tokens"] = output_tokens
    if len(metrics) == 2:
        metrics["total_tokens"] = input_tokens + output_tokens
    return metrics


# Global service instance
chat_service = ChatService()
