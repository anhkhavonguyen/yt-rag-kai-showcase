"""
Shared test setup.

The application reads its settings and builds its service objects when modules
are imported, so placeholder settings must be in the environment before
anything under `app` is imported. Environment variables take precedence over a
developer's local `.env`, so real credentials are never used by the tests.
"""

import os

PLACEHOLDER_SETTINGS = {
    "SUPABASE_URL": "https://placeholder.supabase.co",
    "SUPABASE_ANON_KEY": "placeholder-anon-key",
    "SUPABASE_SERVICE_ROLE_KEY": "placeholder-service-role-key",
    "OPENAI_API_KEY": "placeholder-openai-key",
    "OPENAI_BASE_URL": "",  # empty = default OpenAI endpoint
    "OPENAI_CHAT_MODEL": "test-chat-model",
    "OPENAI_EMBED_MODEL": "test-embed-model",
    "EMBEDDING_DIMENSIONS": "1536",
    "EMBEDDING_BATCH_SIZE": "100",
    "EMBEDDING_SEND_DIMENSIONS": "true",
    "ANTHROPIC_API_KEY": "placeholder-anthropic-key",
    "AI_PROVIDER": "openai",
    "SEED_TOKEN": "",  # empty = /seed open; tests that need a token set it explicitly
    "ENVIRONMENT": "test",
    # Datadog tracing stays off: no key, and switched off as a second guard.
    "DD_API_KEY": "",
    "OBSERVABILITY_ENABLED": "false",
}

# Direct assignment (not setdefault): overwrite anything already in the shell.
os.environ.update(PLACEHOLDER_SETTINGS)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import app.core.database  # noqa: E402
import app.main  # noqa: E402
from app.core import observability  # noqa: E402
from app.services.chat import ChatUnavailableError, chat_service  # noqa: E402
from app.services.embedding import embedding_service  # noqa: E402
from app.services.rag import rag_service  # noqa: E402


class _ForbiddenClient:
    """Stands in for a real API client; any use fails the test."""

    def __init__(self, name: str):
        self._name = name

    def __getattr__(self, attr):
        raise AssertionError(f"Test tried to use the real {self._name} client ({attr})")


@pytest.fixture(autouse=True)
def block_external_services(monkeypatch):
    """Guarantee no test reaches OpenAI, Anthropic or Supabase."""

    def forbid_supabase(*args, **kwargs):
        raise AssertionError("Test tried to create a Supabase client")

    monkeypatch.setattr(app.core.database, "create_client", forbid_supabase)
    monkeypatch.setattr(embedding_service, "openai_client", _ForbiddenClient("OpenAI embeddings"))
    monkeypatch.setattr(chat_service, "client", _ForbiddenClient("chat model"))


@pytest.fixture(autouse=True)
def block_datadog(monkeypatch):
    """Guarantee no test loads the Datadog SDK or sends spans; tracing starts and ends off."""

    attempts: list[str] = []

    # setup() turns its own errors into "tracing off", so record the attempt
    # and fail the test at teardown rather than relying on the raise.
    def forbid_sdk(*args, **kwargs):
        attempts.append("load the Datadog SDK")
        raise AssertionError("Test tried to load the Datadog SDK")

    def forbid_recorder(*args, **kwargs):
        attempts.append("create a DatadogRecorder")
        raise AssertionError("Test tried to create a DatadogRecorder")

    monkeypatch.setattr(observability, "_load_llmobs", forbid_sdk)
    monkeypatch.setattr(observability, "DatadogRecorder", forbid_recorder)
    observability.reset()
    yield
    observability.reset()
    assert not attempts, f"Test tried to {attempts[0]}"


class FakeRecorder:
    """Test double for a tracing backend: keeps every span as a dict, in start order.

    Each span has kind, name, model, provider, parent (the parent span dict or
    None), trace_id, input, output, metadata, metrics, tags, error
    ({"type", "http_status"} or None) and finished.
    """

    def __init__(self):
        self.spans: list[dict] = []
        self.flushes = 0

    def start(self, kind, name, model, provider, parent):
        span = {
            "kind": kind, "name": name, "model": model, "provider": provider, "parent": parent,
            "trace_id": parent["trace_id"] if parent else f"trace-{len(self.spans) + 1}",
            "input": None, "output": None, "metadata": {}, "metrics": {}, "tags": {},
            "error": None, "finished": False,
        }
        self.spans.append(span)
        return span

    def annotate(self, raw, *, input, output, metadata, metrics, tags):
        raw.update(input=input, output=output, metadata=dict(metadata), metrics=dict(metrics), tags=dict(tags))

    def fail(self, raw, error_type, http_status):
        raw["error"] = {"type": error_type, "http_status": http_status}

    def finish(self, raw):
        raw["finished"] = True

    def trace_id(self, raw):
        return raw["trace_id"]

    def flush(self):
        self.flushes += 1

    def of_kind(self, kind: str) -> list[dict]:
        return [span for span in self.spans if span["kind"] == kind]

    def roots(self) -> list[dict]:
        return [span for span in self.spans if span["parent"] is None]

    def children(self, span: dict) -> list[dict]:
        return [child for child in self.spans if child["parent"] is span]

    def dump(self) -> str:
        """Every recorded value as one string, for "appears nowhere" checks."""
        return repr([{key: value for key, value in span.items() if key != "parent"} for span in self.spans])


@pytest.fixture
def recorder():
    """Tracing on, into a FakeRecorder, with text capture on."""
    fake = FakeRecorder()
    observability.use_recorder(fake)
    return fake


class FakeEmbeddingService:
    """Returns a fixed-size vector per text and records what it was asked to embed."""

    def __init__(self, dimensions: int = 3):
        self.dimensions = dimensions
        self.embedded_texts: list[str] = []
        self.error: Exception | None = None  # set to make every call raise

    async def embed_texts(self, texts):
        if self.error:
            raise self.error
        self.embedded_texts.extend(texts)
        return [[float(i)] * self.dimensions for i, _ in enumerate(texts)]

    async def embed_query(self, query):
        return (await self.embed_texts([query]))[0]


class FakeDatabase:
    """In-memory stand-in for the Supabase-backed `db` object."""

    def __init__(self, search_results=None, healthy: bool = True):
        self.search_results = list(search_results or [])
        self.healthy = healthy
        self.upserted: list[dict] = []
        self.stored: dict[str, dict] = {}  # the table's chunks, by chunk ID
        self.writes: list[str] = []  # "upsert" / "delete", in call order
        self.search_calls: list[tuple[list[float], int]] = []
        self.upsert_error: Exception | None = None  # set to make upsert_chunks raise
        self.delete_error: Exception | None = None  # set to make delete_chunks_except raise

    def store(self, *chunk_ids: str) -> None:
        """Put chunks in the table, as if seeded earlier."""
        for chunk_id in chunk_ids:
            self.stored[chunk_id] = {"chunk_id": chunk_id, "source": "old.md", "text": f"old {chunk_id}"}

    async def upsert_chunks(self, chunks):
        self.writes.append("upsert")
        if self.upsert_error:
            raise self.upsert_error
        self.upserted.extend(chunks)
        for chunk in chunks:
            self.stored[chunk["chunk_id"]] = chunk
        return len(chunks)

    async def delete_chunks_except(self, keep_chunk_ids):
        self.writes.append("delete")
        if self.delete_error:
            raise self.delete_error
        keep = set(keep_chunk_ids)
        stale = [chunk_id for chunk_id in self.stored if chunk_id not in keep]
        for chunk_id in stale:
            del self.stored[chunk_id]
        return len(stale)

    async def vector_search(self, query_embedding, top_k=6):
        self.search_calls.append((query_embedding, top_k))
        return self.search_results[:top_k]

    async def health_check(self):
        return self.healthy


class FakeChatService:
    """Returns a canned answer and records the context it was given."""

    def __init__(self, answer: str = "Answer."):
        self.answer = answer
        self.calls: list[tuple[str, list[dict]]] = []
        self.unavailable = False  # set to simulate the model being unavailable

    async def generate_answer(self, query, context_blocks):
        self.calls.append((query, context_blocks))
        if self.unavailable:
            raise ChatUnavailableError("Chat model request failed (RateLimitError)")
        return self.answer


@pytest.fixture
def fake_embedding():
    return FakeEmbeddingService()


@pytest.fixture
def fake_db():
    return FakeDatabase()


@pytest.fixture
def fake_chat():
    return FakeChatService()


@pytest.fixture
def rag(monkeypatch, fake_embedding, fake_db, fake_chat):
    """The real `rag_service` with its external dependencies replaced by fakes."""
    monkeypatch.setattr(rag_service, "embedding_service", fake_embedding)
    monkeypatch.setattr(rag_service, "db", fake_db)
    monkeypatch.setattr(rag_service, "chat_service", fake_chat)
    return rag_service


@pytest.fixture
def client():
    """HTTP client for the app.

    Deliberately not used as a context manager: that would run the FastAPI
    lifespan, which connects to Supabase.
    """
    return TestClient(app.main.app)
