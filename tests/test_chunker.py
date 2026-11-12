"""Document chunking: sizes, overlap and chunk ids."""

import pytest

from app.services.chunker import TextChunker

# chunk_size and overlap are in approximate tokens; the chunker converts them
# to words at 0.75 words per token: 20 -> 15 words per chunk, 8 -> 6 overlap.
CHUNK_SIZE = 20
OVERLAP = 8


@pytest.fixture
def chunker():
    return TextChunker(chunk_size=CHUNK_SIZE, overlap=OVERLAP)


def words(n: int) -> list[str]:
    return [f"w{i}" for i in range(n)]


def test_short_text_becomes_single_chunk(chunker):
    chunks = chunker.chunk_text("  Short   text\nwith  spaces ", "faq.md", "faq")

    assert chunks == [{"chunk_id": "faq#1", "source": "faq.md", "text": "Short text with spaces"}]


@pytest.mark.parametrize("text", ["", "   ", "\n\t "])
def test_empty_or_blank_text_gives_no_chunks(chunker, text):
    assert chunker.chunk_text(text, "empty.md", "empty") == []


def test_long_text_splits_with_sequential_ids_and_exact_overlap(chunker):
    source_words = words(50)
    chunks = chunker.chunk_text(" ".join(source_words), "policy.md", "policy")

    assert len(chunks) > 1
    assert [c["chunk_id"] for c in chunks] == [f"policy#{i}" for i in range(1, len(chunks) + 1)]
    assert all(c["source"] == "policy.md" for c in chunks)

    chunk_words = [c["text"].split() for c in chunks]
    assert all(len(w) <= chunker.words_per_chunk for w in chunk_words)

    # Consecutive chunks share exactly the configured number of overlap words.
    for current, following in zip(chunk_words, chunk_words[1:]):
        assert current[-chunker.overlap_words:] == following[:chunker.overlap_words]
        assert current[-chunker.overlap_words - 1] != following[0]

    # Every word is covered, starting at the first and ending at the last.
    assert chunk_words[0][0] == source_words[0]
    assert chunk_words[-1][-1] == source_words[-1]
    assert set(source_words) == {w for ws in chunk_words for w in ws}


def test_chunk_documents_combines_chunks_from_all_documents(chunker):
    documents = [
        {"chunk_id": "returns", "source": "returns.md", "text": "Items can be returned within 30 days."},
        {"chunk_id": "shipping", "source": "shipping.md", "text": " ".join(words(20))},
    ]

    chunks = chunker.chunk_documents(documents)
    ids = [c["chunk_id"] for c in chunks]

    assert ids[0] == "returns#1"
    assert ids[1:] == [f"shipping#{i}" for i in range(1, len(ids))]
    assert len(ids) > 2  # the 20-word document needed more than one chunk
    assert {c["source"] for c in chunks} == {"returns.md", "shipping.md"}


def test_chunk_documents_uses_defaults_for_missing_fields(chunker):
    chunks = chunker.chunk_documents([{"text": "No id or source."}])

    assert chunks == [{"chunk_id": "doc#1", "source": "unknown", "text": "No id or source."}]
