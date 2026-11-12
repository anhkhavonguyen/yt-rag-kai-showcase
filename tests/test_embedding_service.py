"""Embedding batching and size enforcement, with a fake OpenAI-compatible client."""

import asyncio
import math
from types import SimpleNamespace

import pytest

from app.core.config import get_settings
from app.services.embedding import EmbeddingService, fit_dimensions
from app.services.rag import rag_service


class FakeEmbeddingsAPI:
    """Mimics `client.embeddings.create`, returning vectors of a chosen size."""

    def __init__(self, size: int):
        self.size = size
        self.calls: list[dict] = []

    def create(self, **request):
        self.calls.append(request)
        data = []
        for index, text in enumerate(request["input"]):
            # First value encodes the text number so order can be checked.
            number = int(text.split("-")[1]) if text.startswith("text-") else index
            data.append(SimpleNamespace(index=index, embedding=[float(number + 1)] + [1.0] * (self.size - 1)))
        return SimpleNamespace(data=data)


@pytest.fixture
def settings(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "embedding_dimensions", 1536)
    monkeypatch.setattr(settings, "embedding_batch_size", 100)
    monkeypatch.setattr(settings, "embedding_send_dimensions", True)
    return settings


def service_returning(size: int):
    service = EmbeddingService()
    api = FakeEmbeddingsAPI(size)
    service.openai_client = SimpleNamespace(embeddings=api)
    return service, api


def norm(vector):
    return math.sqrt(sum(x * x for x in vector))


def test_texts_are_sent_in_batches_and_keep_input_order(settings):
    service, api = service_returning(1536)
    texts = [f"text-{i}" for i in range(250)]

    embeddings = asyncio.run(service.embed_texts(texts))

    assert [len(call["input"]) for call in api.calls] == [100, 100, 50]
    assert [call["input"] for call in api.calls] == [texts[:100], texts[100:200], texts[200:]]
    assert len(embeddings) == 250
    assert [e[0] for e in embeddings] == [float(i + 1) for i in range(250)]


def test_exact_size_embedding_is_used_unchanged(settings):
    service, _ = service_returning(1536)

    [embedding] = asyncio.run(service.embed_texts(["text-0"]))

    assert embedding == [1.0] * 1536


def test_longer_embedding_is_truncated_and_normalized(settings):
    service, _ = service_returning(3072)

    [embedding] = asyncio.run(service.embed_texts(["text-4"]))

    assert len(embedding) == 1536
    assert norm(embedding) == pytest.approx(1.0)
    prefix = [5.0] + [1.0] * 1535  # first 1536 values the provider returned
    assert embedding == pytest.approx([x / norm(prefix) for x in prefix])


def test_shorter_embedding_raises_with_both_sizes(settings):
    service, _ = service_returning(768)

    with pytest.raises(ValueError, match=r"768 values.*EMBEDDING_DIMENSIONS is 1536"):
        asyncio.run(service.embed_texts(["text-0"]))


def test_seeding_writes_nothing_when_embeddings_are_too_short(settings, monkeypatch, fake_db):
    service, _ = service_returning(768)
    monkeypatch.setattr(rag_service, "embedding_service", service)
    monkeypatch.setattr(rag_service, "db", fake_db)

    with pytest.raises(ValueError):
        asyncio.run(rag_service.seed_documents([{"chunk_id": "a", "source": "a.md", "text": "Some text."}]))

    assert fake_db.upserted == []


@pytest.mark.parametrize(("send", "expected"), [(True, {"dimensions": 1536}), (False, {})])
def test_dimensions_parameter_follows_setting(settings, monkeypatch, send, expected):
    monkeypatch.setattr(settings, "embedding_send_dimensions", send)
    service, api = service_returning(1536)

    asyncio.run(service.embed_texts(["text-0"]))

    sent = {k: v for k, v in api.calls[0].items() if k == "dimensions"}
    assert sent == expected
    assert api.calls[0]["model"] == service.embed_model


def test_query_embedding_has_configured_size(settings):
    service, _ = service_returning(3072)

    embedding = asyncio.run(service.embed_query("What is the return policy?"))

    assert len(embedding) == 1536


def test_fit_dimensions_handles_zero_prefix():
    assert fit_dimensions([0.0, 0.0, 3.0], 2) == [0.0, 0.0]
