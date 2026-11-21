"""The evaluation report printed at the end of a run."""

from typing import Dict, List, Optional

from .checks import QuestionResult
from .sets import SET_NAMES


def format_report(results: List[QuestionResult], experiment_links: Optional[Dict[str, str]] = None) -> str:
    """One line per question, then pass counts per set and in total, then any experiment links.

        answers
          PASS  who-is-kai
          FAIL  azure-work   cites_expected_source, mentions_required=0.50
        answers 7/8 · guardrails 5/5 · total 12/13
    """
    lines: List[str] = []
    counts: List[str] = []
    for set_name in SET_NAMES:
        group = [result for result in results if result.set == set_name]
        if not group:
            continue
        lines.append(set_name)
        width = max(len(result.id) for result in group)
        for result in group:
            if result.passed:
                lines.append(f"  PASS  {result.id}")
            else:
                lines.append(f"  FAIL  {result.id.ljust(width)}  {result.reason}".rstrip())
        counts.append(f"{set_name} {sum(r.passed for r in group)}/{len(group)}")
    counts.append(f"total {sum(r.passed for r in results)}/{len(results)}")
    lines.append(" · ".join(counts))
    if experiment_links:
        links = "  ".join(f"{name} {url}" for name, url in experiment_links.items())
        lines.append(f"Datadog experiments: {links}")
    return "\n".join(lines)
