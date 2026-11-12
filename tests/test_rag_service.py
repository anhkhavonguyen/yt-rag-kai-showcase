"""RAG pipeline: context preparation, citation extraction, answering and seeding.

External services (embeddings, vector database, chat model) are replaced by the
fakes from conftest.py via the `rag` fixture.
"""

import asyncio

from app.data.default_documents import DEFAULT_DOCUMENTS


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


# --- seeding ----------------------------------------------------------------

def test_seed_documents_stores_chunks_with_embeddings(rag, fake_db, fake_embedding):
    documents = [
        {"chunk_id": "returns", "source": "returns.md", "text": "Items can be returned within 30 days."},
        {"chunk_id": "shipping", "source": "shipping.md", "text": "Orders ship within 2 business days."},
    ]

    inserted = asyncio.run(rag.seed_documents(documents))

    assert inserted == len(fake_db.upserted) == 2
    assert [c["chunk_id"] for c in fake_db.upserted] == ["returns#1", "shipping#1"]
    for chunk in fake_db.upserted:
        assert isinstance(chunk["embedding"], list)
        assert len(chunk["embedding"]) == fake_embedding.dimensions
    assert fake_embedding.embedded_texts == [c["text"] for c in fake_db.upserted]


def test_seed_documents_without_input_uses_default_documents(rag, fake_db):
    inserted = asyncio.run(rag.seed_documents(None))

    assert inserted == len(fake_db.upserted) >= len(DEFAULT_DOCUMENTS)
    seeded_bases = {c["chunk_id"].split("#")[0] for c in fake_db.upserted}
    assert seeded_bases == {d["chunk_id"] for d in DEFAULT_DOCUMENTS}
