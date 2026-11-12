"""HTTP API contract: status codes, response shapes and request validation.

The RAG service and database are replaced with mocks; the FastAPI lifespan
(which would connect to Supabase) is never entered.
"""

from unittest.mock import AsyncMock

import pytest

import app.main


@pytest.fixture
def mock_answer(monkeypatch):
    mock = AsyncMock(return_value={
        "text": "Returns are accepted within 30 days [returns#1].",
        "citations": ["returns#1"],
        "debug": {"top_doc_ids": ["returns#1", "shipping#1"], "latency_ms": 12},
    })
    monkeypatch.setattr(app.main.rag_service, "answer_query", mock)
    return mock


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
    assert body["debug"] == {"top_doc_ids": ["returns#1", "shipping#1"], "latency_ms": 12}
    mock_answer.assert_awaited_once_with(query="What is the return policy?", top_k=6)


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
