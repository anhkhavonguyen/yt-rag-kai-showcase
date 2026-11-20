"""Traces of /answer and /seed: span shape, outcomes, log line, and responses unchanged by tracing.

The real EmbeddingService, ChatService and RAGService run with fake provider
clients and a fake database; spans go to a FakeRecorder.
"""

import asyncio
import logging
from types import SimpleNamespace

import pytest

from app.core import observability
from app.services.chat import ChatService
from app.services.embedding import EmbeddingService
from app.services.rag import NO_RESULTS_TEXT, rag_service
from conftest import FakeDatabase, FakeRecorder

QUESTION = "What can Kai do?"
ANSWER = "Kai builds AI apps [kai_expertise_v1#1]."
ROWS = [
    {"chunk_id": "kai_expertise_v1#1", "source": "expertise.md", "text": "Kai builds AI apps.", "similarity": 0.82},
    {"chunk_id": "kai_current_role_v1#2", "source": "role.md", "text": "Kai leads a team.", "similarity": 0.77},
]


class RateLimitError(Exception):
    status_code = 429


def embeddings_api(error: Exception | None = None):
    def create(**request):
        if error:
            raise error
        return SimpleNamespace(data=[SimpleNamespace(index=i, embedding=[1.0] * 1536)
                                     for i, _ in enumerate(request["input"])])
    return SimpleNamespace(embeddings=SimpleNamespace(create=create))


def chat_api(answer: str = ANSWER, error: Exception | None = None, usage=(812, 95)):
    def create(**kwargs):
        if error:
            raise error
        reported = SimpleNamespace(prompt_tokens=usage[0], completion_tokens=usage[1]) if usage else None
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=answer))], usage=reported)
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


@pytest.fixture
def pipeline(monkeypatch):
    """rag_service with a real EmbeddingService and ChatService on fake clients, and a fake database."""
    embedding = EmbeddingService()
    embedding.openai_client = embeddings_api()
    chat = ChatService()
    chat.client = chat_api()
    db = FakeDatabase(search_results=ROWS)
    monkeypatch.setattr(rag_service, "embedding_service", embedding)
    monkeypatch.setattr(rag_service, "chat_service", chat)
    monkeypatch.setattr(rag_service, "db", db)
    return SimpleNamespace(embedding=embedding, chat=chat, db=db)


def answer(question: str = QUESTION) -> dict:
    return asyncio.run(rag_service.answer_query(question, top_k=6))


# --- /answer -----------------------------------------------------------------


def test_generated_answer_is_one_trace_in_pipeline_order(pipeline, recorder):
    result = answer()

    [root] = recorder.roots()
    assert (root["kind"], root["name"]) == ("workflow", "answer_question")
    assert [(s["kind"], s["name"]) for s in recorder.children(root)] == [
        ("embedding", "embed_texts"),
        ("retrieval", "vector_search"),
        ("llm", "chat_completion"),
    ]
    assert len(recorder.of_kind("llm")) == 1
    assert root["input"] == QUESTION
    assert root["output"] == ANSWER
    assert root["metadata"] == {
        "top_k": 6,
        "answer_mode": "generated",
        "citations": ["kai_expertise_v1#1"],
        "latency_ms": result["debug"]["latency_ms"],
    }
    assert root["tags"] == {"answer_mode": "generated"}
    assert root["error"] is None


def test_nothing_retrieved_has_no_llm_span(pipeline, recorder):
    pipeline.db.search_results = []

    result = answer()

    assert result["text"] == NO_RESULTS_TEXT
    [root] = recorder.roots()
    assert [s["kind"] for s in recorder.children(root)] == ["embedding", "retrieval"]
    assert root["metadata"]["answer_mode"] == "no_results"
    assert recorder.of_kind("retrieval")[0]["output"] == []


def test_model_failure_is_extractive_with_one_failed_llm_span(pipeline, recorder):
    pipeline.chat.client = chat_api(error=RateLimitError("provider-detail-xyz for project 9876"))

    result = answer()

    assert result["debug"]["answer_mode"] == "extractive"
    [root] = recorder.roots()
    [llm] = recorder.of_kind("llm")
    assert llm["error"] == {"type": "RateLimitError", "http_status": 429}
    assert root["metadata"]["answer_mode"] == "extractive"
    assert root["error"] is None
    assert "provider-detail-xyz" not in recorder.dump()
    assert "9876" not in recorder.dump()


def test_embedding_failure_has_only_a_failed_embedding_span(pipeline, recorder):
    pipeline.embedding.openai_client = embeddings_api(error=RateLimitError("quota detail AIza-SECRET-123"))

    result = answer()

    assert result["debug"]["answer_mode"] == "error"
    [root] = recorder.roots()
    [embedding] = recorder.children(root)
    assert embedding["kind"] == "embedding"
    assert embedding["error"] == {"type": "RateLimitError", "http_status": 429}
    assert root["metadata"]["answer_mode"] == "error"
    assert "AIza-SECRET-123" not in recorder.dump()


def test_retrieval_span_lists_each_passage(pipeline, recorder):
    answer()

    [retrieval] = recorder.of_kind("retrieval")
    assert retrieval["input"] == QUESTION
    assert retrieval["metadata"] == {"top_k": 6}
    assert retrieval["output"] == [
        {"id": "kai_expertise_v1#1", "name": "Core expertise", "text": "Kai builds AI apps.", "score": 0.82},
        {"id": "kai_current_role_v1#2", "name": "Current role: DEKRA booking platform",
         "text": "Kai leads a team.", "score": 0.77},
    ]


def test_answer_log_line_carries_the_trace_id(pipeline, recorder, caplog):
    with caplog.at_level(logging.INFO, logger="app.services.rag"):
        answer()

    [line] = [r.getMessage() for r in caplog.records if r.getMessage().startswith("Answer finished")]
    assert "mode=generated" in line
    assert f"trace_id={recorder.roots()[0]['trace_id']}" in line


@pytest.mark.parametrize("break_step", [None, "embedding", "search", "chat"])
def test_answer_log_line_is_written_for_every_outcome_without_trace_id_when_off(pipeline, caplog, break_step):
    if break_step == "embedding":
        pipeline.embedding.openai_client = embeddings_api(error=RateLimitError("x"))
    elif break_step == "search":
        pipeline.db.search_results = []
    elif break_step == "chat":
        pipeline.chat.client = chat_api(error=RateLimitError("x"))

    with caplog.at_level(logging.INFO, logger="app.services.rag"):
        result = answer()

    [line] = [r.getMessage() for r in caplog.records if r.getMessage().startswith("Answer finished")]
    assert f"mode={result['debug']['answer_mode']}" in line
    assert f"latency={result['debug']['latency_ms']}ms" in line
    assert "trace_id" not in line


def test_text_capture_off_keeps_question_and_answer_out_of_the_trace(pipeline):
    fake = FakeRecorder()
    observability.use_recorder(fake, capture_text=False)

    answer()

    dump = fake.dump()
    assert QUESTION not in dump
    assert "Kai builds AI apps" not in dump
    [root] = fake.roots()
    assert root["input"] == f"[text omitted: {len(QUESTION)} chars]"
    assert root["metadata"]["answer_mode"] == "generated"


def test_answer_response_is_the_same_with_tracing_on_and_off(pipeline, client, monkeypatch):
    # Fixed latency, so the two responses can be compared whole.
    monkeypatch.setattr("app.services.rag.time.time", lambda: 1000.0)

    off = client.post("/answer", json={"query": QUESTION})
    observability.use_recorder(FakeRecorder())
    on = client.post("/answer", json={"query": QUESTION})

    assert on.status_code == off.status_code == 200
    assert on.json() == off.json()
    assert on.json()["debug"]["answer_mode"] == "generated"


# --- /seed -------------------------------------------------------------------

DOCS = [
    {"chunk_id": "doc_a_v1", "source": "a.md", "text": "Kai builds retrieval-augmented generation apps."},
    {"chunk_id": "doc_b_v1", "source": "b.md", "text": "Kai leads a team of engineers."},
]


def seed(docs=DOCS):
    return asyncio.run(rag_service.seed_documents(docs))


def test_seed_is_one_trace_with_counts_batches_and_writes(pipeline, recorder, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "embedding_batch_size", 1)
    pipeline.db.store("old_doc_v1#1")

    result = seed()

    chunks = len(pipeline.db.upserted)
    [root] = recorder.roots()
    assert (root["kind"], root["name"]) == ("workflow", "seed_knowledge_base")
    assert root["metadata"] == {
        "documents": 2, "chunks": chunks, "inserted": result.inserted, "removed": 1,
        "latency_ms": root["metadata"]["latency_ms"],
    }
    kinds = [(s["kind"], s["name"]) for s in recorder.children(root)]
    assert kinds == [("embedding", "embed_texts")] * chunks + [("task", "save_chunks"), ("task", "delete_old_chunks")]
    save, delete = recorder.of_kind("task")
    assert save["metadata"] == {"chunks": chunks, "inserted": result.inserted}
    assert delete["metadata"] == {"kept": chunks, "removed": 1}
    assert recorder.of_kind("llm") == []
    assert root["error"] is None


def test_seed_embedding_failure_marks_embedding_and_root_without_writes(pipeline, recorder):
    pipeline.embedding.openai_client = embeddings_api(error=RateLimitError("quota detail"))

    with pytest.raises(RateLimitError):
        seed()

    [root] = recorder.roots()
    assert root["error"] == {"type": "RateLimitError", "http_status": 429}
    assert [s["kind"] for s in recorder.children(root)] == ["embedding"]
    assert recorder.of_kind("embedding")[0]["error"]["type"] == "RateLimitError"
    assert recorder.of_kind("task") == []
    assert "quota detail" not in recorder.dump()


def test_seed_save_failure_marks_the_save_step(pipeline, recorder):
    pipeline.db.upsert_error = RuntimeError("database detail")

    with pytest.raises(RuntimeError):
        seed()

    [root] = recorder.roots()
    [save] = recorder.of_kind("task")
    assert save["name"] == "save_chunks"
    assert save["error"] == {"type": "RuntimeError", "http_status": None}
    assert root["error"]["type"] == "RuntimeError"


def test_seed_trace_holds_no_secrets(pipeline, recorder, client, monkeypatch):
    import app.main
    from conftest import PLACEHOLDER_SETTINGS

    token = "admin-token-for-trace-test-123"
    monkeypatch.setattr(app.main.settings, "seed_token", token)

    client.cookies.set(app.main.admin_session.COOKIE_NAME, "cookie-value-xyz")
    response = client.post("/seed", json={"docs": DOCS}, headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert recorder.roots()[0]["name"] == "seed_knowledge_base"
    dump = recorder.dump()
    for secret in (
        token,
        "cookie-value-xyz",
        PLACEHOLDER_SETTINGS["OPENAI_API_KEY"],
        PLACEHOLDER_SETTINGS["ANTHROPIC_API_KEY"],
        PLACEHOLDER_SETTINGS["SUPABASE_ANON_KEY"],
        PLACEHOLDER_SETTINGS["SUPABASE_SERVICE_ROLE_KEY"],
    ):
        assert secret not in dump


# --- app lifespan -------------------------------------------------------------

@pytest.fixture
def lifespan_db(monkeypatch):
    """Let the app lifespan run without Supabase."""
    import app.main

    async def nothing(*args, **kwargs):
        return None

    async def healthy():
        return True

    for name in ("connect", "initialize_schema", "disconnect"):
        monkeypatch.setattr(app.main.db, name, nothing)
    monkeypatch.setattr(app.main.db, "health_check", healthy)


def test_shutdown_sends_pending_traces_once(lifespan_db, recorder):
    import app.main
    from fastapi.testclient import TestClient

    with TestClient(app.main.app) as client:
        assert client.get("/healthz").status_code == 200
        assert recorder.flushes == 0

    assert recorder.flushes == 1


def test_app_starts_with_tracing_off_when_tracing_fails_to_start(lifespan_db, monkeypatch, caplog):
    import app.main
    from fastapi.testclient import TestClient
    from test_observability import SDK_ENV, FakeLLMObs

    for name in SDK_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(app.main.settings, "dd_api_key", "dd-test-key-123")
    monkeypatch.setattr(app.main.settings, "observability_enabled", True)
    monkeypatch.setattr(observability, "_load_llmobs", lambda: FakeLLMObs(enable_error=RuntimeError("no")))

    with caplog.at_level(logging.WARNING, logger="app.core.observability"):
        with TestClient(app.main.app) as client:
            assert client.get("/healthz").status_code == 200
            with observability.workflow("answer_question"):
                assert observability.current_trace_id() is None

    warnings = [r for r in caplog.records if r.name == "app.core.observability" and r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "could not start" in warnings[0].getMessage()
