"""Chat and embedding clients target the configured OpenAI-compatible endpoint."""

import pytest

from app.core.config import get_settings
from app.services.chat import ChatService
from app.services.embedding import EmbeddingService

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
OPENAI_DEFAULT = "https://api.openai.com/v1/"


@pytest.fixture
def settings(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "ai_provider", "openai")
    return settings


def client_of(service):
    """The OpenAI-compatible client of an EmbeddingService or ChatService."""
    return service.openai_client if isinstance(service, EmbeddingService) else service.client


@pytest.mark.parametrize("service_class", [EmbeddingService, ChatService])
def test_client_uses_configured_base_url(settings, monkeypatch, service_class):
    monkeypatch.setattr(settings, "openai_base_url", GEMINI_BASE_URL)

    assert str(client_of(service_class()).base_url) == GEMINI_BASE_URL


@pytest.mark.parametrize("unset_value", [None, ""])
@pytest.mark.parametrize("service_class", [EmbeddingService, ChatService])
def test_client_defaults_to_openai_when_base_url_unset(settings, monkeypatch, service_class, unset_value):
    # conftest also sets the OPENAI_BASE_URL environment variable to "", which the
    # OpenAI SDK would otherwise pick up as an (unusable) empty base URL.
    monkeypatch.setattr(settings, "openai_base_url", unset_value)

    assert str(client_of(service_class()).base_url) == OPENAI_DEFAULT


@pytest.mark.parametrize("service_class", [EmbeddingService, ChatService])
def test_client_uses_configured_timeout_and_retries(settings, monkeypatch, service_class):
    monkeypatch.setattr(settings, "openai_timeout_seconds", 12.5)
    monkeypatch.setattr(settings, "openai_max_retries", 0)

    client = client_of(service_class())

    assert client.timeout == 12.5
    assert client.max_retries == 0


def test_default_timeout_is_bounded():
    from app.core.config import Settings

    fields = Settings.model_fields
    assert fields["openai_timeout_seconds"].default == 30.0
    assert fields["openai_max_retries"].default == 1


def test_services_use_configured_model_names(settings, monkeypatch):
    monkeypatch.setattr(settings, "openai_chat_model", "gemini-3.5-flash")
    monkeypatch.setattr(settings, "openai_embed_model", "gemini-embedding-2")

    assert ChatService().model == "gemini-3.5-flash"
    assert EmbeddingService().embed_model == "gemini-embedding-2"
