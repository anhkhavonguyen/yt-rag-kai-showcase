"""
Question sets: loading, validation, identity and selection.

Two sets live in evals/questions/:
- answers.json: questions the profile covers. Each names the default documents
  that should be retrieved and cited, and phrases the answer must contain.
- guardrails.json: questions the assistant must deflect. Each names phrases the
  answer must contain and phrases it must not contain.

A `required` entry is a phrase, or a list of alternative phrases of which any
one satisfies it. Phrases match case-insensitively.
"""

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from app.data.default_documents import DOCUMENT_TITLES

QUESTIONS_DIR = Path(__file__).parent / "questions"
SET_NAMES = ("answers", "guardrails")  # also the run order

_ID = re.compile(r"^[a-z0-9-]+$")
# Every field each set's questions must have; any other field is an error.
_FIELDS = {
    "answers": {"id", "question", "expected_documents", "required"},
    "guardrails": {"id", "question", "required", "forbidden"},
}


class QuestionSetError(ValueError):
    """A question set is malformed, or a selection names an unknown question."""


@dataclass(frozen=True)
class Question:
    """One question and what its answer is checked against."""

    id: str
    set: str
    question: str
    required: Tuple[Tuple[str, ...], ...]  # each entry: its alternative phrases
    expected_documents: Tuple[str, ...] = ()  # answers set only
    forbidden: Tuple[str, ...] = ()  # guardrails set only

    def expected_output(self) -> dict:
        """What the answer is checked against, as plain JSON."""
        expected = {"required": [list(alternatives) for alternatives in self.required]}
        if self.set == "answers":
            expected["expected_documents"] = list(self.expected_documents)
        else:
            expected["forbidden"] = list(self.forbidden)
        return expected

    def record(self) -> dict:
        """The question as plain JSON: its identity for hashing, and a dataset record."""
        return {"id": self.id, "question": self.question, **self.expected_output()}


def _nonempty_strings(value, what: str, where: str) -> List[str]:
    if not isinstance(value, list) or not value:
        raise QuestionSetError(f"{where}: {what} must be a non-empty list")
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise QuestionSetError(f"{where}: every entry of {what} must be a non-empty string")
    return value


def _question(raw, set_name: str, index: int, known_documents: Iterable[str]) -> Question:
    where = f"{set_name} question #{index + 1}"
    if not isinstance(raw, dict):
        raise QuestionSetError(f"{where}: must be an object")
    question_id = raw.get("id")
    if not isinstance(question_id, str) or not _ID.match(question_id):
        raise QuestionSetError(f"{where}: id must be lowercase letters, digits and hyphens")
    where = f"{set_name}/{question_id}"

    fields = _FIELDS[set_name]
    missing = sorted(fields - raw.keys())
    unknown = sorted(raw.keys() - fields)
    if missing:
        raise QuestionSetError(f"{where}: missing {', '.join(missing)}")
    if unknown:
        raise QuestionSetError(f"{where}: unknown field {', '.join(unknown)}")

    text = raw["question"]
    if not isinstance(text, str) or not text.strip():
        raise QuestionSetError(f"{where}: question must be a non-empty string")

    required_raw = raw["required"]
    if not isinstance(required_raw, list) or not required_raw:
        raise QuestionSetError(f"{where}: required must be a non-empty list")
    required = []
    for entry in required_raw:
        alternatives = [entry] if isinstance(entry, str) else entry
        required.append(tuple(_nonempty_strings(alternatives, "each required entry", where)))

    expected_documents: Tuple[str, ...] = ()
    forbidden: Tuple[str, ...] = ()
    if set_name == "answers":
        expected_documents = tuple(_nonempty_strings(raw["expected_documents"], "expected_documents", where))
        known = set(known_documents)
        unknown_documents = [doc for doc in expected_documents if doc not in known]
        if unknown_documents:
            raise QuestionSetError(f"{where}: unknown document {', '.join(unknown_documents)}")
    else:
        forbidden = tuple(_nonempty_strings(raw["forbidden"], "forbidden", where))

    return Question(
        id=question_id, set=set_name, question=text, required=tuple(required),
        expected_documents=expected_documents, forbidden=forbidden,
    )


def parse_set(data, set_name: str, known_documents: Iterable[str] = DOCUMENT_TITLES) -> List[Question]:
    """Validate one set's JSON data and return its questions, in file order."""
    if not isinstance(data, dict) or data.get("set") != set_name:
        raise QuestionSetError(f'{set_name}: the file must be an object with "set": "{set_name}"')
    raw_questions = data.get("questions")
    if not isinstance(raw_questions, list) or not raw_questions:
        raise QuestionSetError(f"{set_name}: questions must be a non-empty list")
    return [_question(raw, set_name, i, known_documents) for i, raw in enumerate(raw_questions)]


def load_sets(directory: Path = QUESTIONS_DIR,
              known_documents: Iterable[str] = DOCUMENT_TITLES) -> Dict[str, List[Question]]:
    """Load and validate both sets. Question IDs must be unique across them."""
    sets: Dict[str, List[Question]] = {}
    seen: Dict[str, str] = {}
    for set_name in SET_NAMES:
        path = Path(directory) / f"{set_name}.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise QuestionSetError(f"{set_name}: can't read {path.name} ({type(e).__name__})") from None
        questions = parse_set(data, set_name, known_documents)
        for question in questions:
            if question.id in seen:
                raise QuestionSetError(f"{set_name}/{question.id}: duplicate id (also in {seen[question.id]})")
            seen[question.id] = set_name
        sets[set_name] = questions
    return sets


def select(sets: Dict[str, List[Question]], set_name: Optional[str] = None,
           only: Optional[Sequence[str]] = None) -> List[Question]:
    """The questions to run, answers set first, each set in file order.

    `only` (question IDs from either set) takes precedence over `set_name`.
    """
    ordered = [question for name in SET_NAMES for question in sets.get(name, [])]
    if only:
        known = {question.id for question in ordered}
        unknown = [question_id for question_id in only if question_id not in known]
        if unknown:
            raise QuestionSetError(f"unknown question id {', '.join(unknown)}")
        wanted = set(only)
        return [question for question in ordered if question.id in wanted]
    if set_name:
        if set_name not in SET_NAMES:
            raise QuestionSetError(f"unknown set {set_name}")
        return list(sets.get(set_name, []))
    return ordered


def by_set(questions: Iterable[Question]) -> Dict[str, List[Question]]:
    """Questions grouped by set, in run order; sets with no questions are left out."""
    questions = list(questions)
    grouped: Dict[str, List[Question]] = {}
    for name in SET_NAMES:
        chosen = [question for question in questions if question.set == name]
        if chosen:
            grouped[name] = chosen
    return grouped


def content_hash(questions: Iterable[Question]) -> str:
    """SHA-256 of the questions' canonical JSON. Changes whenever any question changes."""
    canonical = json.dumps([question.record() for question in questions], sort_keys=True,
                           separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
