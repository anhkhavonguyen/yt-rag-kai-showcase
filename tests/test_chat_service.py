"""Chat failures raise ChatUnavailableError without exposing provider error text."""

import asyncio
import logging
from types import SimpleNamespace

import pytest

from app.core.config import get_settings
from app.services.chat import ChatService, ChatUnavailableError

SECRET_DETAIL = "Invalid API key AIza-SECRET-123 for project 9876"
CONTEXT = [{"chunk_id": "returns#1", "text": "Items can be returned within 30 days."}]


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
    service.client = openai_style_client(completion("Returns take 30 days [returns#1]."))

    answer = asyncio.run(service.generate_answer("Return policy?", CONTEXT))

    assert answer == "Returns take 30 days [returns#1]."


def test_provider_error_raises_without_provider_text(service, caplog):
    service.client = openai_style_client(raising)

    with caplog.at_level(logging.ERROR), pytest.raises(ChatUnavailableError) as excinfo:
        asyncio.run(service.generate_answer("Return policy?", CONTEXT))

    assert "AIza-SECRET-123" not in str(excinfo.value)
    assert "AIza-SECRET-123" not in repr(excinfo.value)
    assert excinfo.value.__cause__ is None
    assert "AIza-SECRET-123" not in caplog.text
    assert "ProviderError (HTTP 429)" in caplog.text


@pytest.mark.parametrize("empty", [None, "", "   "])
def test_empty_answer_raises(service, empty):
    service.client = openai_style_client(completion(empty))

    with pytest.raises(ChatUnavailableError):
        asyncio.run(service.generate_answer("Return policy?", CONTEXT))


def test_anthropic_provider_error_also_raises(service):
    service.provider = "anthropic"
    service.client = anthropic_style_client(raising)

    with pytest.raises(ChatUnavailableError) as excinfo:
        asyncio.run(service.generate_answer("Return policy?", CONTEXT))

    assert "AIza-SECRET-123" not in str(excinfo.value)
