"""Chat answers use the profile-assistant prompt, and failures raise ChatUnavailableError without provider text."""

import asyncio
import logging
from types import SimpleNamespace

import pytest

from app.core.config import get_settings
from app.services.chat import SYSTEM_PROMPT, ChatService, ChatUnavailableError

SECRET_DETAIL = "Invalid API key AIza-SECRET-123 for project 9876"
CONTEXT = [{"chunk_id": "kai_overview_v1#1", "text": "Kha Vo, who goes by Kai, is a Team Lead."}]


class ProviderError(Exception):
    status_code = 429


def openai_style_client(create):
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def anthropic_style_client(create):
    return SimpleNamespace(messages=SimpleNamespace(create=create))


def raising(*args, **kwargs):
    raise ProviderError(SECRET_DETAIL)


def completion(text):
    return lambda **kwargs: SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])


@pytest.fixture
def service(monkeypatch):
    monkeypatch.setattr(get_settings(), "ai_provider", "openai")
    return ChatService()


def test_successful_answer_is_returned(service):
    service.client = openai_style_client(completion("Kai is a Team Lead [kai_overview_v1#1]."))

    answer = asyncio.run(service.generate_answer("Who is Kai?", CONTEXT))

    assert answer == "Kai is a Team Lead [kai_overview_v1#1]."


def test_provider_error_raises_without_provider_text(service, caplog):
    service.client = openai_style_client(raising)

    with caplog.at_level(logging.ERROR), pytest.raises(ChatUnavailableError) as excinfo:
        asyncio.run(service.generate_answer("Who is Kai?", CONTEXT))

    assert "AIza-SECRET-123" not in str(excinfo.value)
    assert "AIza-SECRET-123" not in repr(excinfo.value)
    assert excinfo.value.__cause__ is None
    assert "AIza-SECRET-123" not in caplog.text
    assert "ProviderError (HTTP 429)" in caplog.text


@pytest.mark.parametrize("empty", [None, "", "   "])
def test_empty_answer_raises(service, empty):
    service.client = openai_style_client(completion(empty))

    with pytest.raises(ChatUnavailableError):
        asyncio.run(service.generate_answer("Who is Kai?", CONTEXT))


def test_anthropic_provider_error_also_raises(service):
    service.provider = "anthropic"
    service.client = anthropic_style_client(raising)

    with pytest.raises(ChatUnavailableError) as excinfo:
        asyncio.run(service.generate_answer("Who is Kai?", CONTEXT))

    assert "AIza-SECRET-123" not in str(excinfo.value)


# --- the profile-assistant prompt --------------------------------------------

def recording(calls):
    """A provider `create` that records its keyword arguments and answers."""
    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="Kai is a Team Lead."))],
            content=[SimpleNamespace(text="Kai is a Team Lead.")],
        )
    return create


def test_openai_provider_gets_the_system_prompt(service):
    calls = []
    service.client = openai_style_client(recording(calls))

    asyncio.run(service.generate_answer("Who is Kai?", CONTEXT))

    assert calls[0]["messages"][0] == {"role": "system", "content": SYSTEM_PROMPT}


def test_anthropic_provider_gets_the_system_prompt(service):
    calls = []
    service.provider = "anthropic"
    service.client = anthropic_style_client(recording(calls))

    asyncio.run(service.generate_answer("Who is Kai?", CONTEXT))

    assert calls[0]["system"] == SYSTEM_PROMPT


def test_prompt_is_about_kai_in_the_third_person():
    for required in ("Kai", "Kha Vo", "third person", "https://www.linkedin.com/in/khavo2907/"):
        assert required in SYSTEM_PROMPT


def test_prompt_asks_for_plain_text_because_the_page_shows_answers_as_text():
    assert "plain text without Markdown" in SYSTEM_PROMPT
    assert 'start each item\n   on its own line with "- "' in SYSTEM_PROMPT


def test_prompt_has_no_store_wording():
    lowered = SYSTEM_PROMPT.lower()
    for wording in ("returns", "shipping", "sizing", "customer support"):
        assert wording not in lowered
