"""Saves each run to its own folder, so it can be studied and run afterwards.

    orchestrator_runs/<YYYYMMDD-HHMMSS>/
        round-1/api.py, round-1/index.html, round-1/review.json
        round-2/...                       every round folder is a complete, runnable app
        final/api.py, final/index.html    the last app (not written when the run failed)
        transcript.md                     the task, who ran each round, every verdict, the outcome

Files are written the moment each one is ready. The recorder only writes files:
it never runs, imports or serves the generated code.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .agents import Review

API = "api.py"
PAGE = "index.html"
_AUTHORS = {API: "the back-end agent", PAGE: "the front-end agent"}


def file_size(text: str) -> str:
    """A file's size for people to read, such as "2.4 KB"."""
    return f"{len(text.encode('utf-8')) / 1024:.1f} KB"


@dataclass
class _RoundRecord:
    files: dict[str, tuple[str, bool]] = field(default_factory=dict)  # name -> (text, rebuilt this round)
    review: Review | None = None


class RunRecorder:
    """Creates a new run folder and writes the run's files into it."""

    def __init__(self, out_dir: str | Path = "orchestrator_runs", now: datetime | None = None):
        base = Path(out_dir)
        base.mkdir(parents=True, exist_ok=True)
        stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
        self.folder = _new_folder(base, stamp)
        self.task = ""
        self.max_rounds = 0
        self._rounds: dict[int, _RoundRecord] = {}

    @property
    def final_folder(self) -> Path:
        return self.folder / "final"

    def start(self, task: str, max_rounds: int) -> None:
        self.task = task
        self.max_rounds = max_rounds

    def save_file(self, round_no: int, name: str, text: str, rebuilt: bool) -> None:
        """Write api.py or index.html for a round. `rebuilt` is False for a file kept from the round before."""
        self._write(f"round-{round_no}/{name}", text)
        self._rounds.setdefault(round_no, _RoundRecord()).files[name] = (text, rebuilt)

    def save_review(self, round_no: int, review: Review) -> None:
        self._write(f"round-{round_no}/review.json", json.dumps(review.model_dump(), indent=2, ensure_ascii=False) + "\n")
        self._rounds.setdefault(round_no, _RoundRecord()).review = review

    def finish(self, outcome: str, rounds: int, final_files: dict[str, str] | None, failure: str | None = None) -> None:
        """Write final/ (when the run ends with an app) and transcript.md.

        `outcome` is the readable result, such as "approved after 2 rounds".
        """
        for name, text in (final_files or {}).items():
            self._write(f"final/{name}", text)
        self._write("transcript.md", self._transcript(outcome, rounds, bool(final_files), failure))

    def _transcript(self, outcome: str, rounds: int, has_final_app: bool, failure: str | None) -> str:
        lines = [
            f"# Orchestrator run {self.folder.name}",
            "",
            f"- **Task:** {self.task}",
            f"- **Outcome:** {outcome}",
            f"- **Round limit:** {self.max_rounds}",
        ]
        if failure:
            lines.append(f"- **Failure:** {failure}")

        for round_no in range(1, rounds + 1):
            record = self._rounds.get(round_no, _RoundRecord())
            lines += ["", f"## Round {round_no}", ""]
            for name in (API, PAGE):
                if name not in record.files:
                    lines.append(f"- `{name}`: none")
                    continue
                text, rebuilt = record.files[name]
                how = f"written by {_AUTHORS[name]}" if rebuilt else "kept from the previous round"
                lines.append(f"- `{name}`: {how} ({file_size(text)})")
            review = record.review
            if review is None:
                lines.append("- Verdict: none")
                continue
            if not review.readable:
                lines.append("- Warning: the reviewer's reply was not a valid verdict, so it counts as changes requested.")
            lines.append(f"- Verdict: {'approved' if review.approved else 'changes requested'}")
            lines.append(f"- Summary: {review.summary}")
            if review.issues:
                lines.append("- Issues:")
                lines += [f"  - [{issue.owner}] " + issue.text.replace("\n", "\n    ") for issue in review.issues]

        lines += ["", "## Final app", ""]
        if has_final_app:
            lines.append(
                f"`final/` holds `api.py` and `index.html` from round {rounds}. Read both files before you run "
                "them, then run `python -m uvicorn api:app` in `final/` and open http://127.0.0.1:8000."
            )
        else:
            lines.append("None: the run failed before the app was reviewed to the end.")
        return "\n".join(lines) + "\n"

    def _write(self, relative: str, text: str) -> None:
        path = self.folder / relative
        path.parent.mkdir(exist_ok=True)
        path.write_text(text, encoding="utf-8")


def _new_folder(base: Path, stamp: str) -> Path:
    """Create base/stamp, or base/stamp-2, stamp-3, ... if a run already took the name."""
    n = 1
    while True:
        folder = base / (stamp if n == 1 else f"{stamp}-{n}")
        try:
            folder.mkdir()  # fails if the folder exists, so two runs never share one
            return folder
        except FileExistsError:
            n += 1
