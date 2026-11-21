"""
Deterministic checks for evaluation runs, and the rule for when a question passes.

Each evaluator is a plain function `fn(input_data, output_data, expected_output)`,
the shape Datadog experiments call. Its function name is the label shown in
Datadog. Every evaluator returns the same type for every question: no `None`
for "not applicable", which Datadog would record as a different metric type.
That's why the two question sets have separate evaluator lists.

`output_data` is what the task returned for a question:
    {"answer", "answer_mode", "citations", "passage_ids", "latency_ms"}
It is None when the task itself raised.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from app.services import answer_checks

_NO_OUTPUT = {"answer": "", "answer_mode": "error", "citations": [], "passage_ids": []}


def _output(output_data) -> Dict[str, Any]:
    return output_data if isinstance(output_data, dict) else _NO_OUTPUT


def _mentions(answer: str, phrase: str) -> bool:
    return phrase.lower() in (answer or "").lower()


def _documents(chunk_ids) -> set:
    return {answer_checks.document_id(chunk_id) for chunk_id in chunk_ids}


# --- Evaluators ----------------------------------------------------------------


def answer_mode(input_data, output_data, expected_output) -> str:
    """How the answer was produced: generated, extractive, no_results or error."""
    return _output(output_data)["answer_mode"]


def retrieval_hit(input_data, output_data, expected_output) -> bool:
    """An expected document is among the passages given to the model."""
    return bool(_documents(_output(output_data)["passage_ids"]) & set(expected_output["expected_documents"]))


def cites_expected_source(input_data, output_data, expected_output) -> bool:
    """The answer cites an expected document."""
    return bool(_documents(_output(output_data)["citations"]) & set(expected_output["expected_documents"]))


def mentions_required(input_data, output_data, expected_output) -> float:
    """The fraction of required entries the answer mentions (any alternative counts)."""
    answer = _output(output_data)["answer"]
    required = expected_output["required"]
    hits = sum(1 for alternatives in required if any(_mentions(answer, phrase) for phrase in alternatives))
    return hits / len(required)


def avoids_forbidden(input_data, output_data, expected_output) -> bool:
    """The answer contains none of the forbidden phrases."""
    answer = _output(output_data)["answer"]
    return not any(_mentions(answer, phrase) for phrase in expected_output["forbidden"])


def citations_valid(input_data, output_data, expected_output) -> bool:
    """Every bracketed marker names a passage the model was given (same rule as live)."""
    output = _output(output_data)
    return answer_checks.citations_valid(output["answer"], output["passage_ids"])


def plain_text(input_data, output_data, expected_output) -> bool:
    """No Markdown in the answer (same rule as live)."""
    return answer_checks.plain_text(_output(output_data)["answer"])


EVALUATORS: Dict[str, List[Callable]] = {
    "answers": [answer_mode, retrieval_hit, cites_expected_source, mentions_required, citations_valid, plain_text],
    "guardrails": [answer_mode, mentions_required, avoids_forbidden, citations_valid, plain_text],
}


# --- Pass rule -------------------------------------------------------------------


# Report order for failed checks, so local and Datadog runs list them the same way.
_CHECK_ORDER = ["retrieval_hit", "cites_expected_source", "mentions_required", "avoids_forbidden",
                "citations_valid", "plain_text"]


def failed_checks(checks: Dict[str, Any]) -> List[str]:
    """The content checks that failed (a false boolean, or mentions_required below 1), in check order."""
    failed = []
    ordered = sorted(checks, key=lambda label: (_CHECK_ORDER.index(label) if label in _CHECK_ORDER
                                                else len(_CHECK_ORDER), label))
    for label in ordered:
        value = checks[label]
        if label == "answer_mode":
            continue
        if label == "mentions_required":
            if not isinstance(value, (int, float)) or value < 1:
                failed.append(f"mentions_required={value:.2f}" if isinstance(value, (int, float)) else label)
        elif value is not True:
            failed.append(label)
    return failed


def unavailable_reason(mode: Optional[str]) -> Optional[str]:
    """Why an answer couldn't be judged on content, or None for a generated answer."""
    if mode == "generated":
        return None
    if mode == "extractive":
        return "model unavailable (extractive)"
    if mode == "no_results":
        return "search unavailable (no_results: is the knowledge base seeded?)"
    return f"search unavailable ({mode})"


def passes(checks: Dict[str, Any]) -> bool:
    """A question passes with a generated answer and every check passing."""
    return checks.get("answer_mode") == "generated" and not failed_checks(checks)


@dataclass
class QuestionResult:
    """One question's outcome in a run."""

    id: str
    set: str
    output: Optional[Dict[str, Any]]
    checks: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None  # the task's error type, if it raised

    @property
    def passed(self) -> bool:
        return self.error is None and passes(self.checks)

    @property
    def reason(self) -> str:
        """Why the question failed, for the report; empty when it passed."""
        if self.error:
            return f"task error: {self.error}"
        unavailable = unavailable_reason(self.checks.get("answer_mode"))
        if unavailable:
            return unavailable
        return ", ".join(failed_checks(self.checks))


def score(question, output: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Run the question's set's evaluators on one output, by label."""
    input_data = {"question": question.question}
    expected = question.expected_output()
    return {evaluator.__name__: evaluator(input_data, output, expected) for evaluator in EVALUATORS[question.set]}


# --- Summary evaluators (one value per experiment) ---------------------------------


def pass_rate(inputs, outputs, expected_outputs, evaluators_results) -> float:
    """The fraction of questions that passed."""
    count = len(outputs)
    if not count:
        return 0.0
    rows = [{label: values[i] for label, values in evaluators_results.items() if i < len(values)}
            for i in range(count)]
    return sum(1 for checks in rows if passes(checks)) / count


def retrieval_hit_rate(inputs, outputs, expected_outputs, evaluators_results) -> float:
    """The fraction of questions whose expected document was retrieved."""
    values = evaluators_results.get("retrieval_hit", [])
    return sum(1 for value in values if value is True) / len(values) if values else 0.0


SUMMARY_EVALUATORS: Dict[str, List[Callable]] = {
    "answers": [pass_rate, retrieval_hit_rate],
    "guardrails": [pass_rate],
}
