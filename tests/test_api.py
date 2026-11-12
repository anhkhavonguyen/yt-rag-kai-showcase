"""HTTP API contract: status codes, response shapes and request validation.

The RAG service and database are replaced with mocks; the FastAPI lifespan
(which would connect to Supabase) is never entered.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import app.main
from app.services.chat import ChatService


@pytest.fixture
def mock_answer(monkeypatch):
    mock = AsyncMock(return_value={
        "text": "Returns are accepted within 30 days [returns#1].",
        "citations": ["returns#1"],
        "debug": {"top_doc_ids": ["returns#1", "shipping#1"], "latency_ms": 12, "answer_mode": "generated"},
    })
    monkeypatch.setattr(app.main.rag_service, "answer_query", mock)
    return mock


ADMIN_TOKEN = "s3cret-admin-token"


@pytest.fixture
def seed_token(monkeypatch):
    """Configure SEED_TOKEN for the duration of a test."""
    monkeypatch.setattr(app.main.settings, "seed_token", ADMIN_TOKEN)
    return ADMIN_TOKEN


@pytest.fixture
def mock_seed(monkeypatch):
    mock = AsyncMock(return_value=5)
    monkeypatch.setattr(app.main.rag_service, "seed_documents", mock)
    return mock


def test_root_returns_api_information(client):
    response = client.get("/")

    assert response.status_code == 200
    assert "endpoints" in response.json()


@pytest.mark.parametrize(
    ("db_healthy", "expected_status"),
    [(True, "ok"), (False, "degraded")],
)
def test_healthz_reports_database_state(client, monkeypatch, db_healthy, expected_status):
    monkeypatch.setattr(app.main.db, "health_check", AsyncMock(return_value=db_healthy))

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": expected_status, "database_connected": db_healthy}


def test_seed_without_body_seeds_default_documents(client, mock_seed):
    response = client.post("/seed")

    assert response.status_code == 200
    assert response.json() == {"inserted": 5}
    mock_seed.assert_awaited_once_with(None)


def test_seed_with_documents_passes_them_to_the_rag_service(client, mock_seed):
    docs = [
        {"chunk_id": "returns", "source": "returns.md", "text": "Items can be returned within 30 days."},
        {"chunk_id": "shipping", "source": "shipping.md", "text": "Orders ship within 2 business days."},
    ]

    response = client.post("/seed", json={"docs": docs})

    assert response.status_code == 200
    assert response.json() == {"inserted": 5}
    mock_seed.assert_awaited_once_with(docs)


def test_answer_returns_text_citations_and_debug_info(client, mock_answer):
    response = client.post("/answer", json={"query": "What is the return policy?"})

    assert response.status_code == 200
    body = response.json()
    assert body["text"] == "Returns are accepted within 30 days [returns#1]."
    assert body["citations"] == ["returns#1"]
    assert body["debug"] == {
        "top_doc_ids": ["returns#1", "shipping#1"],
        "latency_ms": 12,
        "answer_mode": "generated",
    }
    mock_answer.assert_awaited_once_with(query="What is the return policy?", top_k=6)


def test_answer_falls_back_to_passages_without_leaking_provider_error(client, rag, fake_db, monkeypatch):
    """Full path: a real ChatService whose provider call fails with a rate limit."""

    class RateLimitError(Exception):
        status_code = 429

    def failing_create(**kwargs):
        raise RateLimitError("Quota exceeded for project 9876, key AIza-SECRET-123")

    chat = ChatService()
    chat.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=failing_create)))
    monkeypatch.setattr(rag, "chat_service", chat)
    fake_db.search_results = [
        {"chunk_id": "returns#1", "source": "returns.md", "text": "Items can be returned within 30 days."},
        {"chunk_id": "shipping#1", "source": "shipping.md", "text": "Orders ship in 2 business days."},
    ]

    response = client.post("/answer", json={"query": "What is the return policy?"})

    assert response.status_code == 200
    body = response.json()
    assert body["debug"]["answer_mode"] == "extractive"
    assert body["citations"] == ["returns#1", "shipping#1"]
    assert "AIza-SECRET-123" not in response.text
    assert "9876" not in response.text


def test_answer_reports_error_without_leaking_embedding_failure(client, rag, fake_embedding):
    fake_embedding.error = RuntimeError("Invalid API key AIza-SECRET-123")

    response = client.post("/answer", json={"query": "What is the return policy?"})

    assert response.status_code == 200
    body = response.json()
    assert body["debug"]["answer_mode"] == "error"
    assert body["citations"] == []
    assert "AIza-SECRET-123" not in response.text


def test_answer_passes_requested_top_k(client, mock_answer):
    response = client.post("/answer", json={"query": "Shipping times?", "top_k": 20})

    assert response.status_code == 200
    mock_answer.assert_awaited_once_with(query="Shipping times?", top_k=20)


@pytest.mark.parametrize(
    "payload",
    [
        {"query": "Shipping times?", "top_k": 0},
        {"query": "Shipping times?", "top_k": 21},
        {"top_k": 5},
    ],
    ids=["top_k-too-small", "top_k-too-large", "missing-query"],
)
def test_answer_rejects_invalid_requests(client, mock_answer, payload):
    response = client.post("/answer", json=payload)

    assert response.status_code == 422
    mock_answer.assert_not_awaited()


# --- admin token for /seed ------------------------------------------------------

@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer wrong-token"}, {"Authorization": "Basic czNjcmV0"}],
    ids=["missing", "wrong", "not-bearer"],
)
def test_seed_rejects_missing_or_wrong_token(client, seed_token, mock_seed, headers):
    response = client.post("/seed", headers=headers)

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    mock_seed.assert_not_awaited()


def test_seed_accepts_correct_token(client, seed_token, mock_seed):
    response = client.post("/seed", headers={"Authorization": f"Bearer {seed_token}"})

    assert response.status_code == 200
    assert response.json() == {"inserted": 5}
    mock_seed.assert_awaited_once_with(None)


@pytest.mark.parametrize("unset", [None, ""])
def test_seed_is_open_when_no_token_configured(client, monkeypatch, mock_seed, unset):
    monkeypatch.setattr(app.main.settings, "seed_token", unset)

    response = client.post("/seed")

    assert response.status_code == 200
    mock_seed.assert_awaited_once()


# --- admin pages (sign-in and the session: tests/test_admin_sign_in.py) ----------

def test_admin_token_check_endpoint_is_removed(client, seed_token, mock_seed):
    response = client.get("/admin/verify", headers={"Authorization": f"Bearer {seed_token}"})

    assert response.status_code == 404
    mock_seed.assert_not_awaited()


def test_other_endpoints_do_not_need_the_token(client, seed_token, mock_answer, monkeypatch):
    monkeypatch.setattr(app.main.db, "health_check", AsyncMock(return_value=True))

    assert client.post("/answer", json={"query": "Shipping times?"}).status_code == 200
    assert client.get("/healthz").status_code == 200
    assert client.get("/documents").status_code == 200
    assert client.get("/").status_code == 200
    assert client.get("/chat").status_code == 200
    assert client.get("/admin/login", follow_redirects=False).status_code == 200


# --- pages ----------------------------------------------------------------------

def test_chat_page_has_no_knowledge_base_editing(client):
    response = client.get("/chat")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    for admin_only in ("Knowledge Base Editor", "/seed", "/admin"):
        assert admin_only not in response.text


@pytest.mark.parametrize(
    ("environment", "token", "warns"),
    [("production", "", True), ("production", None, True), ("production", "set", False), ("development", "", False)],
)
def test_startup_warns_when_production_seed_is_unprotected(monkeypatch, caplog, environment, token, warns):
    monkeypatch.setattr(app.main.settings, "environment", environment)
    monkeypatch.setattr(app.main.settings, "seed_token", token)

    with caplog.at_level("WARNING", logger="app.main"):
        app.main.warn_if_seed_unprotected()

    assert ("SEED_TOKEN is not set" in caplog.text) is warns
