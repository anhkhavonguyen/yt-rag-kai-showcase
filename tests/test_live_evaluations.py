"""Live answer checks: rule-based evaluations on each traced /answer.

The real RAGService runs over the fakes from conftest (embedding, database,
chat); spans and evaluations go to a FakeRecorder.
"""

import asyncio
import logging

import pytest

from app.core import observability
from app.services import answer_checks
from conftest import FakeRecorder

QUESTION = "What can Kai do?"
ROWS = [
    {"chunk_id": "skills#1", "text": "Kai builds AI apps.", "similarity": 0.82},
    {"chunk_id": "experience#2", "text": "Kai leads a team.", "similarity": 0.77},
]


@pytest.fixture
def search(fake_db):
    fake_db.search_results = list(ROWS)
    return fake_db


def answer(rag) -> dict:
    return asyncio.run(rag.answer_query(QUESTION, top_k=6))


def root_evaluations(recorder) -> dict:
    [root] = recorder.roots()
    return recorder.evaluations(root)


def test_generated_answer_carries_all_four_checks(rag, search, fake_chat, recorder):
    fake_chat.answer = "Kai builds AI apps [skills#1]."

    answer(rag)

    assert root_evaluations(recorder) == {
        "retrieval_top_score": (0.82, None),
        "cites_sources": (True, None),
        "citations_valid": (True, "pass"),
        "plain_text": (True, "pass"),
    }
    [root] = recorder.roots()
    assert {e["label"]: e["metric_type"] for e in root["evaluations"]} == {
        "retrieval_top_score": "score", "cites_sources": "boolean",
        "citations_valid": "boolean", "plain_text": "boolean",
    }
    assert all(not child["evaluations"] for child in recorder.children(root))


def test_made_up_citation_fails_citations_valid(rag, search, fake_chat, recorder):
    fake_chat.answer = "Kai builds AI apps [skills#1] and expects a salary [salary#9]."

    answer(rag)

    assert root_evaluations(recorder)["citations_valid"] == (False, "fail")
    assert root_evaluations(recorder)["cites_sources"] == (True, None)


def test_markdown_fails_plain_text(rag, search, fake_chat, recorder):
    fake_chat.answer = "**Kai** builds AI apps [skills#1]."

    answer(rag)

    assert root_evaluations(recorder)["plain_text"] == (False, "fail")


def test_answer_without_citations(rag, search, fake_chat, recorder):
    fake_chat.answer = "Hi! Ask me anything about Kai."

    answer(rag)

    evaluations = root_evaluations(recorder)
    assert evaluations["cites_sources"] == (False, None)
    assert evaluations["citations_valid"] == (True, "pass")


def test_fallback_answer_carries_only_the_retrieval_score(rag, search, fake_chat, recorder):
    fake_chat.unavailable = True

    result = answer(rag)

    assert result["debug"]["answer_mode"] == "extractive"
    assert root_evaluations(recorder) == {"retrieval_top_score": (0.82, None)}


def test_nothing_retrieved_carries_no_checks(rag, fake_db, recorder):
    fake_db.search_results = []

    result = answer(rag)

    assert result["debug"]["answer_mode"] == "no_results"
    assert root_evaluations(recorder) == {}


def test_failure_before_the_model_carries_no_checks(rag, search, fake_embedding, recorder):
    fake_embedding.error = RuntimeError("embedding quota")

    result = answer(rag)

    assert result["debug"]["answer_mode"] == "error"
    assert root_evaluations(recorder) == {}


def test_rows_without_scores_leave_out_the_retrieval_score(rag, fake_db, fake_chat, recorder):
    fake_db.search_results = [{"chunk_id": "skills#1", "text": "Kai builds AI apps."}]
    fake_chat.answer = "Kai builds AI apps [skills#1]."

    answer(rag)

    assert "retrieval_top_score" not in root_evaluations(recorder)
    assert root_evaluations(recorder)["citations_valid"] == (True, "pass")


def test_checks_hold_no_text_with_text_capture_off(rag, search, fake_chat):
    fake_chat.answer = "Kai builds AI apps [skills#1]."
    fake = FakeRecorder()
    observability.use_recorder(fake, capture_text=False)

    answer(rag)

    [root] = fake.roots()
    assert set(fake.evaluations(root)) == {"retrieval_top_score", "cites_sources", "citations_valid", "plain_text"}
    assert QUESTION not in repr(root["evaluations"])
    assert "Kai builds AI apps" not in repr(root["evaluations"])
    assert all(isinstance(e["value"], (bool, int, float)) for e in root["evaluations"])


class EvaluateFailsRecorder(FakeRecorder):
    def evaluate(self, raw, label, metric_type, value, assessment):
        raise RuntimeError("intake rejected")


def answer_body(client) -> dict:
    response = client.post("/answer", json={"query": QUESTION})
    assert response.status_code == 200
    body = response.json()
    body["debug"].pop("latency_ms")
    return body


def test_failing_evaluations_leave_the_response_unchanged(rag, search, fake_chat, client):
    fake_chat.answer = "Kai builds AI apps [skills#1]."
    expected = answer_body(client)  # tracing off

    observability.use_recorder(EvaluateFailsRecorder())

    assert answer_body(client) == expected


def test_failing_rules_are_logged_and_leave_the_response_unchanged(rag, search, fake_chat, client, monkeypatch,
                                                                   caplog):
    fake_chat.answer = "Kai builds AI apps [skills#1]."
    expected = answer_body(client)

    def broken(*args, **kwargs):
        raise ValueError("rule broke")

    monkeypatch.setattr(answer_checks, "citations_valid", broken)
    observability.use_recorder(FakeRecorder())
    with caplog.at_level(logging.WARNING, logger="app.services.rag"):
        assert answer_body(client) == expected

    assert "Answer checks failed (ValueError)" in caplog.text


def test_tracing_off_computes_no_checks(rag, search, fake_chat, monkeypatch):
    fake_chat.answer = "Kai builds AI apps [skills#1]."

    def forbidden(*args, **kwargs):
        raise AssertionError("answer checks ran with tracing off")

    monkeypatch.setattr(answer_checks, "citations_valid", forbidden)
    monkeypatch.setattr(answer_checks, "plain_text", forbidden)

    result = answer(rag)

    assert result["debug"]["answer_mode"] == "generated"
