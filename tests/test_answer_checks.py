"""Answer rules shared by live answer checks and offline evaluation."""

import pytest

from app.services.answer_checks import citation_markers, citations_valid, document_id, plain_text

PASSAGES = ["kai_overview_v1#1", "kai_expertise_v1#1"]


def test_citation_markers_in_order():
    answer = "Kai leads a team [kai_overview_v1#1] and builds apps [kai_expertise_v1#1]."
    assert citation_markers(answer) == ["kai_overview_v1#1", "kai_expertise_v1#1"]


def test_no_markers_is_valid():
    assert citations_valid("Hello! Ask me about Kai.", PASSAGES) is True


def test_markers_naming_given_passages_are_valid():
    assert citations_valid("Kai is a Team Lead [kai_overview_v1#1].", PASSAGES) is True


def test_marker_the_model_made_up_is_invalid():
    answer = "Kai is a Team Lead [kai_overview_v1#1] and expects a salary [kai_salary_v1#1]."
    assert citations_valid(answer, PASSAGES) is False


def test_empty_answer_has_no_markers():
    assert citation_markers("") == []
    assert citations_valid(None, PASSAGES) is True


@pytest.mark.parametrize("answer", [
    "Kai works with **Azure**.",
    "Kai writes `C#` daily.",
    "# About Kai\nKai is a Team Lead.",
    "Intro\n  # Heading\nText",
])
def test_markdown_is_not_plain_text(answer):
    assert plain_text(answer) is False


@pytest.mark.parametrize("answer", [
    "Kai works with C# and .NET.",
    "Kai's skills:\n- Azure\n- .NET",
    "",
])
def test_plain_text(answer):
    assert plain_text(answer) is True


def test_document_id():
    assert document_id("kai_dxc_v1#2") == "kai_dxc_v1"
    assert document_id("kai_dxc_v1") == "kai_dxc_v1"
