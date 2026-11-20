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


# --- tracing: one LLM span per model request ---------------------------------

def completion_with_usage(text, usage):
    def create(**kwargs):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
            usage=usage,
        )
    return create


def test_llm_span_records_model_messages_answer_and_tokens(service, recorder):
    service.client = openai_style_client(
        completion_with_usage("Kai is a Team Lead.", SimpleNamespace(prompt_tokens=812, completion_tokens=95))
    )

    asyncio.run(service.generate_answer("Who is Kai?", CONTEXT))

    [span] = recorder.spans
    assert (span["kind"], span["name"]) == ("llm", "chat_completion")
    assert (span["model"], span["provider"]) == ("test-chat-model", "openai")
    assert span["input"][0] == {"role": "system", "content": SYSTEM_PROMPT}
    assert span["input"][1]["role"] == "user" and "Who is Kai?" in span["input"][1]["content"]
    assert span["output"] == [{"role": "assistant", "content": "Kai is a Team Lead."}]
    assert span["metadata"] == {"temperature": get_settings().temperature, "max_tokens": 1000}
    assert span["metrics"] == {"input_tokens": 812, "output_tokens": 95, "total_tokens": 907}
    assert span["error"] is None


def test_llm_span_has_no_token_counts_when_provider_reports_none(service, recorder):
    service.client = openai_style_client(completion_with_usage("Kai is a Team Lead.", None))

    asyncio.run(service.generate_answer("Who is Kai?", CONTEXT))

    assert recorder.spans[0]["metrics"] == {}


def test_failed_request_is_one_llm_span_with_type_and_status_only(service, recorder):
    def failing(**kwargs):
        raise ProviderError("provider-detail-xyz")

    service.client = openai_style_client(failing)

    with pytest.raises(ChatUnavailableError):
        asyncio.run(service.generate_answer("Who is Kai?", CONTEXT))

    [span] = recorder.spans
    assert span["error"] == {"type": "ProviderError", "http_status": 429}
    assert "provider-detail-xyz" not in recorder.dump()


def test_empty_answer_marks_the_llm_span_failed(service, recorder):
    service.client = openai_style_client(completion(""))

    with pytest.raises(ChatUnavailableError):
        asyncio.run(service.generate_answer("Who is Kai?", CONTEXT))

    assert recorder.spans[0]["error"] == {"type": "EmptyAnswer", "http_status": None}


def test_anthropic_request_is_traced_with_its_usage(monkeypatch, recorder):
    monkeypatch.setattr(get_settings(), "ai_provider", "anthropic")
    service = ChatService()
    service.client = anthropic_style_client(lambda **kwargs: SimpleNamespace(
        content=[SimpleNamespace(text="Kai is a Team Lead.")],
        usage=SimpleNamespace(input_tokens=700, output_tokens=40),
    ))

    asyncio.run(service.generate_answer("Who is Kai?", CONTEXT))

    [span] = recorder.spans
    assert span["provider"] == "anthropic"
    assert span["metrics"] == {"input_tokens": 700, "output_tokens": 40, "total_tokens": 740}
    assert span["output"] == [{"role": "assistant", "content": "Kai is a Team Lead."}]


def test_gemini_endpoint_is_labelled_google(monkeypatch):
    monkeypatch.setattr(get_settings(), "ai_provider", "openai")
    monkeypatch.setattr(get_settings(), "openai_base_url", "https://generativelanguage.googleapis.com/v1beta/openai/")

    assert ChatService().provider_label == "google"
