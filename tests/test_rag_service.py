"""RAG pipeline: context preparation, citation extraction, answering and seeding.

External services (embeddings, vector database, chat model) are replaced by the
fakes from conftest.py via the `rag` fixture.
"""

import asyncio

import pytest

from app.data.default_documents import DEFAULT_DOCUMENTS
from app.services.rag import SeedResult


def result(chunk_id: str, text: str = "text", similarity: float = 0.9) -> dict:
    return {"chunk_id": chunk_id, "source": f"{chunk_id.split('#')[0]}.md", "text": text, "similarity": similarity}


# --- context preparation ----------------------------------------------------

def test_prepare_context_keeps_one_chunk_per_document_in_rank_order(rag):
    results = [result("a#1"), result("a#2"), result("b#1"), result("b#3")]

    context = rag._prepare_context(results)

    assert [c["chunk_id"] for c in context] == ["a#1", "b#1"]


def test_prepare_context_is_capped_at_four_blocks(rag):
    results = [result(f"doc{i}#1") for i in range(6)]

    context = rag._prepare_context(results)

    assert [c["chunk_id"] for c in context] == ["doc0#1", "doc1#1", "doc2#1", "doc3#1"]


# --- citation extraction ----------------------------------------------------

def test_extract_citations_drops_ids_not_in_context(rag):
    context = [result("returns#1"), result("shipping#1")]

    citations = rag._extract_citations("See [returns#1] and [made-up#7].", context)

    assert citations == ["returns#1"]


def test_extract_citations_removes_duplicates_and_keeps_first_seen_order(rag):
    context = [result("returns#1"), result("shipping#1")]

    citations = rag._extract_citations(
        "First [shipping#1], then [returns#1], again [shipping#1] and [returns#1].", context
    )

    assert citations == ["shipping#1", "returns#1"]


# --- answering --------------------------------------------------------------

def test_answer_query_without_search_results_says_it_lacks_information(rag, fake_db, fake_chat):
    fake_db.search_results = []

    answer = asyncio.run(rag.answer_query("What is the return policy?", top_k=5))

    assert "don't have enough information" in answer["text"]
    assert answer["citations"] == []
    assert answer["debug"]["top_doc_ids"] == []
    assert answer["debug"]["answer_mode"] == "no_results"
    assert fake_chat.calls == []  # the language model is not called


def test_answer_query_returns_answer_with_citations_from_context(rag, fake_db, fake_chat):
    fake_db.search_results = [result("returns#1"), result("returns#2"), result("shipping#1")]
    fake_chat.answer = "Returns are accepted within 30 days [returns#1]. See also [invented#1]."

    answer = asyncio.run(rag.answer_query("What is the return policy?", top_k=3))

    assert answer["text"] == fake_chat.answer
    assert answer["citations"] == ["returns#1"]
    assert answer["debug"]["top_doc_ids"] == ["returns#1", "shipping#1"]
    assert isinstance(answer["debug"]["latency_ms"], int)
    assert answer["debug"]["answer_mode"] == "generated"

    # The requested top_k reaches the search, and the model sees the deduplicated context.
    assert fake_db.search_calls[0][1] == 3
    query, context_blocks = fake_chat.calls[0]
    assert query == "What is the return policy?"
    assert [c["chunk_id"] for c in context_blocks] == ["returns#1", "shipping#1"]


def test_answer_query_returns_passages_when_model_unavailable(rag, fake_db, fake_chat):
    fake_db.search_results = [
        result("returns#1", "Items can be returned within 30 days."),
        result("returns#2", "Refunds take 5 days."),
        result("shipping#1", "Orders ship in 2 business days."),
    ]
    fake_chat.unavailable = True

    answer = asyncio.run(rag.answer_query("What is the return policy?"))

    assert answer["debug"]["answer_mode"] == "extractive"
    assert answer["citations"] == ["returns#1", "shipping#1"]
    assert answer["debug"]["top_doc_ids"] == ["returns#1", "shipping#1"]
    assert answer["text"] == (
        "A generated answer isn't available right now. Here are the most relevant passages:\n\n"
        "[returns#1] Items can be returned within 30 days.\n\n"
        "[shipping#1] Orders ship in 2 business days."
    )


def test_answer_query_reports_error_without_provider_text_when_embedding_fails(rag, fake_embedding, fake_chat):
    fake_embedding.error = RuntimeError("429 quota exceeded for key AIza-SECRET-123")

    answer = asyncio.run(rag.answer_query("What is the return policy?"))

    assert answer["debug"]["answer_mode"] == "error"
    assert answer["text"] == "I couldn't search the knowledge base right now. Please try again shortly."
    assert answer["citations"] == []
    assert "AIza-SECRET-123" not in str(answer)
    assert fake_chat.calls == []


# --- answer sources ---------------------------------------------------------

def test_sources_hold_the_passage_and_title_of_each_citation(rag, fake_db, fake_chat):
    fake_db.search_results = [
        result("kai_overview_v1#1", "Kha Vo, who goes by Kai, is a Team Lead."),
        result("kai_expertise_v1#1", "Kai works with .NET and Azure."),
    ]
    fake_chat.answer = "Kai works with .NET and Azure [kai_expertise_v1#1]."

    answer = asyncio.run(rag.answer_query("What can Kai do?"))

    assert answer["citations"] == ["kai_expertise_v1#1"]
    assert answer["sources"] == [
        {"chunk_id": "kai_expertise_v1#1", "title": "Core expertise", "text": "Kai works with .NET and Azure."},
    ]


def test_sources_follow_citation_order(rag, fake_db, fake_chat):
    fake_db.search_results = [result("kai_overview_v1#1"), result("kai_expertise_v1#1")]
    fake_chat.answer = "First [kai_expertise_v1#1], then [kai_overview_v1#1]."

    answer = asyncio.run(rag.answer_query("Who is Kai?"))

    assert [s["chunk_id"] for s in answer["sources"]] == ["kai_expertise_v1#1", "kai_overview_v1#1"]
    assert [s["title"] for s in answer["sources"]] == ["Core expertise", "Who Kai is"]


def test_fallback_answer_has_a_source_per_passage(rag, fake_db, fake_chat):
    fake_db.search_results = [result("kai_overview_v1#1", "Overview."), result("kai_dxc_v1#1", "DXC.")]
    fake_chat.unavailable = True

    answer = asyncio.run(rag.answer_query("Who is Kai?"))

    assert answer["debug"]["answer_mode"] == "extractive"
    assert [(s["chunk_id"], s["text"]) for s in answer["sources"]] == [
        ("kai_overview_v1#1", "Overview."),
        ("kai_dxc_v1#1", "DXC."),
    ]


def test_a_chunk_from_another_document_is_titled_by_its_chunk_id(rag, fake_db, fake_chat):
    fake_db.search_results = [result("notes#1", "Some notes.")]
    fake_chat.answer = "See [notes#1]."

    answer = asyncio.run(rag.answer_query("Notes?"))

    assert answer["sources"] == [{"chunk_id": "notes#1", "title": "notes#1", "text": "Some notes."}]


def test_no_sources_without_results_or_on_error(rag, fake_db, fake_embedding):
    fake_db.search_results = []
    assert asyncio.run(rag.answer_query("Who is Kai?"))["sources"] == []

    fake_embedding.error = RuntimeError("quota")
    assert asyncio.run(rag.answer_query("Who is Kai?"))["sources"] == []


# --- seeding ----------------------------------------------------------------

def test_seed_documents_stores_chunks_with_embeddings(rag, fake_db, fake_embedding):
    documents = [
        {"chunk_id": "overview", "source": "profile.md", "text": "Kai is a Team Lead."},
        {"chunk_id": "expertise", "source": "profile.md", "text": "Kai works with .NET and Azure."},
    ]

    result = asyncio.run(rag.seed_documents(documents))

    assert result == SeedResult(inserted=2, removed=0)
    assert [c["chunk_id"] for c in fake_db.upserted] == ["overview#1", "expertise#1"]
    for chunk in fake_db.upserted:
        assert isinstance(chunk["embedding"], list)
        assert len(chunk["embedding"]) == fake_embedding.dimensions
    assert fake_embedding.embedded_texts == [c["text"] for c in fake_db.upserted]
    assert fake_db.writes == ["upsert", "delete"]  # delete only after the save


def test_seed_documents_without_input_uses_default_documents(rag, fake_db):
    result = asyncio.run(rag.seed_documents(None))

    assert result.inserted == len(DEFAULT_DOCUMENTS)
    assert set(fake_db.stored) == {f"{doc['chunk_id']}#1" for doc in DEFAULT_DOCUMENTS}


# --- a seed replaces the knowledge base -------------------------------------

POLICY_CHUNKS = ("policy_returns_v1#1", "policy_shipping_v1#1", "sizing_guide_v1#1", "support_contact_v1#1")


def test_seed_removes_the_old_store_chunks(rag, fake_db):
    fake_db.store(*POLICY_CHUNKS)

    result = asyncio.run(rag.seed_documents(None))

    assert result.removed == 4
    assert set(fake_db.stored) == {f"{doc['chunk_id']}#1" for doc in DEFAULT_DOCUMENTS}


def test_seed_drops_the_chunks_a_shorter_document_no_longer_has(rag, fake_db):
    fake_db.store("overview#1", "overview#2")

    result = asyncio.run(rag.seed_documents([{"chunk_id": "overview", "source": "p.md", "text": "Kai, in short."}]))

    assert result == SeedResult(inserted=1, removed=1)
    assert list(fake_db.stored) == ["overview#1"]
    assert fake_db.stored["overview#1"]["text"] == "Kai, in short."


def test_seeding_the_same_documents_again_removes_nothing(rag, fake_db):
    asyncio.run(rag.seed_documents(None))
    first = dict(fake_db.stored)

    result = asyncio.run(rag.seed_documents(None))

    assert result.removed == 0
    assert set(fake_db.stored) == set(first)
    assert all(fake_db.stored[cid]["text"] == first[cid]["text"] for cid in first)


def test_failed_embedding_changes_nothing(rag, fake_db, fake_embedding):
    fake_db.store(*POLICY_CHUNKS)
    fake_embedding.error = RuntimeError("quota used up")

    with pytest.raises(RuntimeError):
        asyncio.run(rag.seed_documents(None))

    assert fake_db.writes == []
    assert set(fake_db.stored) == set(POLICY_CHUNKS)


def test_failed_save_deletes_nothing(rag, fake_db):
    fake_db.store(*POLICY_CHUNKS)
    fake_db.upsert_error = RuntimeError("database unavailable")

    with pytest.raises(RuntimeError):
        asyncio.run(rag.seed_documents(None))

    assert fake_db.writes == ["upsert"]
    assert set(fake_db.stored) == set(POLICY_CHUNKS)


def test_failed_delete_keeps_the_new_chunks_and_a_retry_finishes(rag, fake_db):
    fake_db.store(*POLICY_CHUNKS)
    fake_db.delete_error = RuntimeError("delete failed")
    profile_chunks = {f"{doc['chunk_id']}#1" for doc in DEFAULT_DOCUMENTS}

    with pytest.raises(RuntimeError):
        asyncio.run(rag.seed_documents(None))

    assert set(fake_db.stored) == profile_chunks | set(POLICY_CHUNKS)

    fake_db.delete_error = None
    result = asyncio.run(rag.seed_documents(None))

    assert result.removed == 4
    assert set(fake_db.stored) == profile_chunks


def test_blank_documents_change_nothing(rag, fake_db, fake_embedding):
    fake_db.store(*POLICY_CHUNKS)

    result = asyncio.run(rag.seed_documents([{"chunk_id": "blank", "source": "b.md", "text": "   "}]))

    assert result == SeedResult(inserted=0, removed=0)
    assert fake_embedding.embedded_texts == []
    assert fake_db.writes == []
    assert set(fake_db.stored) == set(POLICY_CHUNKS)
