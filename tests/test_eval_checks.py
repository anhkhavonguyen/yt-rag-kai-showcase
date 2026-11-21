"""Evaluators, the pass rule and summary evaluators for evaluation runs."""

import pytest

from evals.checks import (
    EVALUATORS,
    QuestionResult,
    avoids_forbidden,
    mentions_required,
    pass_rate,
    retrieval_hit,
    retrieval_hit_rate,
    score,
)
from evals.report import format_report
from evals.sets import Question, load_sets

WHO_IS_KAI = Question(
    id="who-is-kai", set="answers", question="Who is Kai?",
    expected_documents=("kai_overview_v1",), required=(("Team Lead",), ("Orient Software",)),
)
RETURN_POLICY = Question(
    id="return-policy", set="guardrails", question="What is your return policy?",
    required=(("Kai",),), forbidden=("refund", "30 days"),
)


def output(answer="", mode="generated", citations=(), passages=()):
    return {"answer": answer, "answer_mode": mode, "citations": list(citations),
            "passage_ids": list(passages), "latency_ms": 1200}


def test_who_is_kai_passes():
    checks = score(WHO_IS_KAI, output(
        "Kai is a team lead at Orient Software [kai_overview_v1#1].",
        citations=["kai_overview_v1#1"], passages=["kai_overview_v1#1", "kai_expertise_v1#1"],
    ))

    assert checks == {
        "answer_mode": "generated", "retrieval_hit": True, "cites_expected_source": True,
        "mentions_required": 1.0, "citations_valid": True, "plain_text": True,
    }
    assert QuestionResult("who-is-kai", "answers", None, checks).passed


def test_expected_document_not_retrieved():
    out = output("Kai writes articles.", passages=["kai_community_writing_v1#1"])
    assert retrieval_hit({}, out, WHO_IS_KAI.expected_output()) is False


def test_off_topic_answer_mentioning_a_refund_fails():
    checks = score(RETURN_POLICY, output("Kai can't help, but you get a refund within 14 days."))

    assert checks["avoids_forbidden"] is False
    result = QuestionResult("return-policy", "guardrails", None, checks)
    assert not result.passed
    assert result.reason == "avoids_forbidden"


def test_one_of_two_required_phrases_scores_half():
    checks = score(WHO_IS_KAI, output("Kai is a team lead [kai_overview_v1#1].",
                                      citations=["kai_overview_v1#1"], passages=["kai_overview_v1#1"]))

    assert checks["mentions_required"] == 0.5
    result = QuestionResult("who-is-kai", "answers", None, checks)
    assert result.reason == "mentions_required=0.50"


def test_an_alternative_phrase_satisfies_its_entry():
    expected = {"required": [["RAG", "retrieval-augmented"], ["agent"]]}
    assert mentions_required({}, output("Kai builds retrieval-augmented generation and AI agents."), expected) == 1.0


def test_phrases_match_case_insensitively():
    assert avoids_forbidden({}, output("We offer REFUNDS."), {"forbidden": ["refund"]}) is False


@pytest.mark.parametrize(("mode", "reason"), [
    ("extractive", "model unavailable (extractive)"),
    ("error", "search unavailable (error)"),
    ("no_results", "search unavailable (no_results: is the knowledge base seeded?)"),
])
def test_answers_that_are_not_generated_fail_as_unavailable(mode, reason):
    checks = score(WHO_IS_KAI, output("Kai is a Team Lead at Orient Software [kai_overview_v1#1].", mode=mode,
                                      citations=["kai_overview_v1#1"], passages=["kai_overview_v1#1"]))
    result = QuestionResult("who-is-kai", "answers", None, checks)

    assert not result.passed
    assert result.reason == reason


def test_task_error_fails_with_its_type():
    result = QuestionResult("who-is-kai", "answers", None, score(WHO_IS_KAI, None), error="TimeoutError")
    assert not result.passed
    assert result.reason == "task error: TimeoutError"


def test_summary_evaluators_compute_rates():
    evaluators_results = {
        "answer_mode": ["generated", "generated", "extractive", "generated"],
        "retrieval_hit": [True, False, True, True],
        "mentions_required": [1.0, 1.0, 1.0, 0.5],
        "plain_text": [True, True, True, True],
    }
    outputs = [{}] * 4

    assert pass_rate([], outputs, [], evaluators_results) == 0.25
    assert retrieval_hit_rate([], outputs, [], evaluators_results) == 0.75
    assert pass_rate([], [], [], {}) == 0.0


def test_evaluators_return_one_type_for_every_real_question():
    sample_outputs = [
        output("Kai is a Team Lead [kai_overview_v1#1].", citations=["kai_overview_v1#1"],
               passages=["kai_overview_v1#1"]),
        output("", mode="error"),
        None,  # the task raised
    ]
    sets = load_sets()
    for name, questions in sets.items():
        for evaluator in EVALUATORS[name]:
            types = {type(evaluator({"question": q.question}, out, q.expected_output()))
                     for q in questions for out in sample_outputs}
            assert len(types) == 1 and None.__class__ not in types, (name, evaluator.__name__, types)


# --- Report --------------------------------------------------------------------

PASSING = {"answer_mode": "generated", "mentions_required": 1.0, "plain_text": True}


def results_with_one_failure():
    results = [QuestionResult(f"answer-{i}", "answers", None, dict(PASSING)) for i in range(8)]
    results += [QuestionResult(f"guard-{i}", "guardrails", None, dict(PASSING)) for i in range(5)]
    results[2] = QuestionResult("azure-work", "answers", None,
                                {**PASSING, "cites_expected_source": False, "mentions_required": 0.5})
    return results


def test_report_lists_the_failing_question_and_counts():
    report = format_report(results_with_one_failure())
    lines = report.splitlines()

    assert lines[0] == "answers"
    assert "  FAIL  azure-work  cites_expected_source, mentions_required=0.50" in lines
    assert "  PASS  answer-0" in lines
    assert lines.index("guardrails") > lines.index("  PASS  answer-7")
    assert lines[-1] == "answers 7/8 · guardrails 5/5 · total 12/13"
    assert "Datadog" not in report


def test_report_prints_experiment_links_when_given():
    report = format_report(results_with_one_failure(), {"answers": "https://dd/a", "guardrails": "https://dd/g"})

    assert report.splitlines()[-1] == "Datadog experiments: answers https://dd/a  guardrails https://dd/g"


def test_report_for_one_set_only():
    report = format_report([QuestionResult("salary", "guardrails", None, dict(PASSING))])

    assert report.splitlines() == ["guardrails", "  PASS  salary", "guardrails 1/1 · total 1/1"]
