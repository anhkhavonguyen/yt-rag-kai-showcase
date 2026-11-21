"""
Rules for checking an answer, shared by live answer checks and offline evaluation.

Pure functions, no I/O. The same rule gives the same result for the same answer
whether it runs on a live /answer trace (app/services/rag.py) or in an
evaluation run (evals/), so the two never disagree.

Design: openspec/changes/datadog-rag-evaluation/design.md, Decision 1.
"""

import re
from typing import Iterable, List

# Every "[...]" in an answer. The assistant is told to cite passages as [chunk_id].
_MARKER = re.compile(r"\[([^\]]+)\]")
# A Markdown heading: "#" at the start of a line, after optional spaces.
_HEADING = re.compile(r"^[ \t]*#", re.MULTILINE)


def citation_markers(answer: str) -> List[str]:
    """The contents of every bracketed marker in the answer, in order."""
    return _MARKER.findall(answer or "")


def citations_valid(answer: str, passage_ids: Iterable[str]) -> bool:
    """Whether every marker names a passage the model was given. No markers is valid."""
    known = set(passage_ids)
    return all(marker in known for marker in citation_markers(answer))


def plain_text(answer: str) -> bool:
    """Whether the answer is free of Markdown: no "**", no backtick, no heading line."""
    text = answer or ""
    return "**" not in text and "`" not in text and not _HEADING.search(text)


def document_id(chunk_id: str) -> str:
    """The document a chunk belongs to: the chunk ID before "#"."""
    return chunk_id.split("#")[0]
