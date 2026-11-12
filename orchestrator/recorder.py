"""Saves each run to its own folder, so it can be studied and run afterwards.

    orchestrator_runs/<YYYYMMDD-HHMMSS>/
        round-1/api.py, round-1/index.html, round-1/review.json
        round-1/calls/01-backend.md, ...  every model call of the round: prompt, message, reply
        round-2/...                       every round folder is a complete, runnable app
        final/api.py, final/index.html    the last app (not written when the run failed)
        transcript.md                     the task, who ran each round, every verdict, the outcome
        run.log                           the orchestrator's log lines, as printed

Files are written the moment each one is ready. The recorder only writes files:
it never runs, imports or serves the generated code.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .agents import Review
from .llm import ModelCallError, ModelClient
from .project import Project, file_diff, manifest_data

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
    # Project mode only:
    changed: dict[str, str] = field(default_factory=dict)  # path -> owner that changed it this round
    rejected: list[tuple[str, str]] = field(default_factory=list)  # (owner, path) returned but not allowed


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
        self.current_round = 0  # set by the orchestrator, so calls land in the right round folder
        self._calls_in_round: dict[int, int] = {}

    @property
    def final_folder(self) -> Path:
        return self.folder / "final"

    def start(self, task: str, max_rounds: int) -> None:
        self.task = task
        self.max_rounds = max_rounds

    def begin_round(self, round_no: int) -> None:
        self.current_round = round_no

    def log_line(self, line: str) -> None:
        """Append one of the orchestrator's log lines to run.log."""
        with open(self.folder / "run.log", "a", encoding="utf-8", newline="\n") as log:
            log.write(line + "\n")

    def save_call(self, agent: str, system: str, user: str, reply: str | None = None,
                  failure: str | None = None) -> None:
        """Write one model call to round-N/calls/NN-<agent>.md: what was sent and what came back.

        `failure` is the error type only (such as "RateLimitError (HTTP 429)"), never the provider's message.
        """
        round_no = self.current_round
        number = self._calls_in_round.get(round_no, 0) + 1
        self._calls_in_round[round_no] = number
        answer = reply if failure is None else f"failed: {failure}"
        text = (
            f"# Call {number:02d}: {agent} (round {round_no})\n\n"
            f"## System prompt\n\n{system}\n\n"
            f"## Message\n\n{user}\n\n"
            f"## Reply\n\n{answer}\n"
        )
        self._write(f"round-{round_no}/calls/{number:02d}-{agent}.md", text)

    # --- Project mode -----------------------------------------------------------------
    #
    #   round-N/files/<path>    every --edit file as it stands after round N
    #   final/files/<path>      the files the run ends with
    #   changes.diff            the final files against the project's originals
    #   manifest.json           project folder, task, starting hashes, outcome (read by --apply)

    def start_project(self, task: str, max_rounds: int, project: Project) -> None:
        self.start(task, max_rounds)
        self.project = project

    def save_project_round(
        self, round_no: int, files: dict[str, str | None], changed: dict[str, str], rejected: list[tuple[str, str]]
    ) -> None:
        """Write every --edit file that exists after round N. `changed` maps path -> owner for this round's changes."""
        for path, text in files.items():
            if text is not None:
                self._write(f"round-{round_no}/files/{path}", text)
        record = self._rounds.setdefault(round_no, _RoundRecord())
        record.changed = dict(changed)
        record.rejected = list(rejected)

    def finish_project(
        self, outcome_key: str, outcome: str, rounds: int, final_files: dict[str, str | None] | None,
        failure: str | None = None,
    ) -> None:
        """Write final/files/, changes.diff and manifest.json (when the run ends with files) and transcript.md.

        `outcome_key` is "approved", "not approved" or "failed"; `outcome` is the readable result.
        """
        project = self.project
        if final_files is not None:
            diffs = []
            for edit in project.edits:
                text = final_files.get(edit.path)
                if text is not None:
                    self._write(f"final/files/{edit.path}", text)
                diffs.append(file_diff(edit.path, edit.original, text))
            self._write("changes.diff", "".join(diffs))
        manifest = manifest_data(project, self.task, outcome_key, rounds)
        self._write("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
        self._write("transcript.md", self._project_transcript(outcome, rounds, final_files is not None, failure))

    def _project_transcript(self, outcome: str, rounds: int, has_files: bool, failure: str | None) -> str:
        project = self.project
        first_line = self.task.strip().splitlines()[0] if self.task.strip() else ""
        lines = [
            f"# Orchestrator run {self.folder.name} (project mode)",
            "",
            f"- **Task:** {first_line} (the full task is in `manifest.json`)",
            f"- **Project:** {project.root}",
            f"- **Outcome:** {outcome}",
            f"- **Round limit:** {self.max_rounds}",
        ]
        if failure:
            lines.append(f"- **Failure:** {failure}")
        lines.append("- **Files the agents may change:**")
        for edit in project.edits:
            start = "" if edit.original is not None else ", new"
            lines.append(f"  - `{edit.path}` ({edit.owner}{start})")
        if project.context:
            lines.append("- **Context files:** " + ", ".join(f"`{path}`" for path, _ in project.context))

        for round_no in range(1, rounds + 1):
            record = self._rounds.get(round_no, _RoundRecord())
            lines += ["", f"## Round {round_no}", ""]
            if record.changed:
                for path, owner in record.changed.items():
                    lines.append(f"- `{path}`: changed by the {owner} agent")
            else:
                lines.append("- No file changed")
            for owner, path in record.rejected:
                lines.append(f"- Not saved: the {owner} agent returned `{path}`, which is not in its --edit list")
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

        lines += ["", "## Result", ""]
        if has_files and outcome.startswith("approved"):
            lines.append(
                f"`final/files/` holds the files from round {rounds}, and `changes.diff` shows every change. "
                f"Read the diff, then apply it with `python -m orchestrator --apply {self.folder}`."
            )
        elif has_files:
            lines.append(
                "`final/files/` holds the last files and `changes.diff` shows them against the project. "
                "Only approved runs can be applied."
            )
        else:
            lines.append("None: the run failed before the files were reviewed to the end.")
        return "\n".join(lines) + "\n"

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
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")  # the same bytes on every system


class RecordingClient:
    """Wraps the shared model client for one agent and saves every call it makes.

    Each agent gets its own wrapper, so the saved file can name the agent. The
    reply is saved as returned; a failed call saves its error type only.
    """

    def __init__(self, client: ModelClient, recorder: RunRecorder, agent: str):
        self.client = client
        self.recorder = recorder
        self.agent = agent

    def complete(self, system: str, user: str) -> str:
        try:
            reply = self.client.complete(system, user)
        except ModelCallError as error:
            self.recorder.save_call(self.agent, system, user, failure=error.error_type)
            raise
        self.recorder.save_call(self.agent, system, user, reply=reply)
        return reply


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
