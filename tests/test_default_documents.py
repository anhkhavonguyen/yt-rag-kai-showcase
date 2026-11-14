"""The default knowledge base: ten titled documents about Kha Vo (Kai), public facts only.

Whether a document names someone other than Kha Vo is checked by review, not
here: a denylist of names would put those names in the repo.
"""

import re

import pytest

from app.data.default_documents import DEFAULT_DOCUMENTS, DOCUMENT_TITLES, LINKEDIN_URL
from app.services.chunker import TextChunker

EXPECTED_IDS = {
    "kai_overview_v1",
    "kai_current_role_v1",
    "kai_cloud_production_v1",
    "kai_earlier_projects_v1",
    "kai_dxc_v1",
    "kai_expertise_v1",
    "kai_ai_focus_v1",
    "kai_education_certifications_v1",
    "kai_career_direction_v1",
    "kai_community_writing_v1",
}

STORE_WORDING = ["return policy", "shipping", "sizing", "customer support"]
PRIVATE_WORDING = ["profile views", "impressions", "search appearances", "followers", "connections", "etown"]

EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
# A run of digits and phone separators; it counts as a phone number when it holds 9+ digits.
PHONE_CANDIDATE = re.compile(r"\+?\d[\d\s().-]{6,}\d")
WORD12 = re.compile(r"\b[a-z0-9]{12}\b")

DOC_IDS = [doc["chunk_id"] for doc in DEFAULT_DOCUMENTS]


def by_id(chunk_id: str) -> dict:
    return next(doc for doc in DEFAULT_DOCUMENTS if doc["chunk_id"] == chunk_id)


def looks_like_phone_number(text: str) -> bool:
    return any(sum(c.isdigit() for c in run) >= 9 for run in PHONE_CANDIDATE.findall(text))


def looks_like_credential_id(text: str) -> bool:
    """A 12-character lowercase-letter-and-digit token with both letters and digits."""
    return any(
        any(c.isdigit() for c in token) and any(c.isalpha() for c in token)
        for token in WORD12.findall(text)
    )


# --- topics and titles ------------------------------------------------------

def test_the_ten_topic_documents_with_unique_ids():
    assert len(DOC_IDS) == len(set(DOC_IDS))
    assert set(DOC_IDS) == EXPECTED_IDS


def test_every_document_has_a_unique_title():
    titles = [doc["title"] for doc in DEFAULT_DOCUMENTS]
    assert all(title.strip() for title in titles)
    assert len(titles) == len(set(titles))
    assert DOCUMENT_TITLES == {doc["chunk_id"]: doc["title"] for doc in DEFAULT_DOCUMENTS}


def test_every_source_is_the_linkedin_profile():
    assert LINKEDIN_URL == "https://www.linkedin.com/in/khavo2907/"
    assert all(doc["source"] == LINKEDIN_URL for doc in DEFAULT_DOCUMENTS)


def test_documents_endpoint_returns_the_titled_documents(client):
    documents = client.get("/documents").json()["documents"]

    assert {doc["chunk_id"] for doc in documents} == EXPECTED_IDS
    assert all(doc["title"] for doc in documents)


# --- each document reads on its own -----------------------------------------

@pytest.mark.parametrize("chunk_id", DOC_IDS)
def test_every_document_names_kai(chunk_id):
    text = by_id(chunk_id)["text"]
    assert "Kai" in text or "Kha Vo" in text


def test_overview_says_kha_vo_goes_by_kai():
    assert "Kha Vo, who goes by Kai" in by_id("kai_overview_v1")["text"]


@pytest.mark.parametrize("chunk_id", DOC_IDS)
def test_every_document_is_one_chunk(chunk_id):
    doc = by_id(chunk_id)

    chunks = TextChunker().chunk_text(doc["text"], doc["source"], doc["chunk_id"])

    assert [c["chunk_id"] for c in chunks] == [f"{chunk_id}#1"]


# --- what stays out ---------------------------------------------------------

@pytest.mark.parametrize("chunk_id", DOC_IDS)
def test_no_store_or_private_wording(chunk_id):
    text = by_id(chunk_id)["text"].lower()
    for wording in STORE_WORDING + PRIVATE_WORDING:
        assert wording not in text, f"{chunk_id} mentions {wording!r}"


@pytest.mark.parametrize("chunk_id", DOC_IDS)
def test_no_contact_or_credential_details(chunk_id):
    text = by_id(chunk_id)["text"]
    assert not EMAIL.search(text)
    assert not looks_like_phone_number(text)
    assert not looks_like_credential_id(text)


@pytest.mark.parametrize(
    "text, found",
    [
        ("Write to kai@example.com", "email"),
        ("Call +84 912 345 678", "phone"),
        ("Credential ID 8ef23mi7ch5g", "credential"),
        ("From September 2014 to June 2016 (2010 to 2014), a 30-member team", None),
    ],
)
def test_the_detectors_catch_what_they_should(text, found):
    assert bool(EMAIL.search(text)) == (found == "email")
    assert looks_like_phone_number(text) == (found == "phone")
    assert looks_like_credential_id(text) == (found == "credential")
