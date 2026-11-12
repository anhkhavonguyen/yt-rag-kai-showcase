"""The orchestrator: a plain Python loop that runs three agents.

It is the only part that holds state (the task, api.py, index.html and the
latest review) and the only part that decides what happens next. No model is
asked to decide anything.

    round 1:   backend(task)                       -> api.py
               frontend(task, api.py)              -> index.html
               reviewer(task, api.py, index.html)  -> verdict, issues tagged backend / frontend
    round 2+:  backend again only if it has issues
               frontend again (its issues, or the new api.py)
               reviewer again
    ...        until the reviewer approves, the round limit is reached, or a call fails
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from .agents import BACKEND, BOTH, FRONTEND, BackendAgent, FrontendAgent, Issue, Review, ReviewerAgent
from .llm import ModelCallError
from .recorder import API, PAGE, RunRecorder, file_size

APPROVED = "approved"
NOT_APPROVED = "not approved"
FAILED = "failed"

# Exit status of `python -m orchestrator` for each outcome.
EXIT_CODES = {APPROVED: 0, NOT_APPROVED: 2, FAILED: 1}


@dataclass
class RunResult:
    outcome: str  # APPROVED, NOT_APPROVED or FAILED
    rounds: int  # rounds started
    final_api: str | None = None  # None when the run failed
    final_page: str | None = None
    open_issues: list[Issue] = field(default_factory=list)  # set when NOT_APPROVED
    failure: str | None = None  # set when FAILED, e.g. "reviewer failed: RateLimitError (HTTP 429)"


class Orchestrator:
    def __init__(
        self,
        backend: BackendAgent,
        frontend: FrontendAgent,
        reviewer: ReviewerAgent,
        recorder: RunRecorder,
        max_rounds: int = 3,
        on_event: Callable[[str], None] = print,
    ):
        self.backend = backend
        self.frontend = frontend
        self.reviewer = reviewer
        self.recorder = recorder
        self.max_rounds = max_rounds
        self.on_event = on_event  # receives one progress line per step

    def run(self, task: str) -> RunResult:
        self.recorder.start(task, self.max_rounds)
        api: str | None = None  # the current api.py
        page: str | None = None  # the current index.html
        review: Review | None = None  # the latest review

        for round_no in range(1, self.max_rounds + 1):
            self.on_event(f"== Round {round_no} of {self.max_rounds} ==")
            first_round = review is None
            backend_issues = issues_for(review, BACKEND)
            frontend_issues = issues_for(review, FRONTEND)
            try:
                # 1. Back end: always in round 1; afterwards only when it has issues to fix.
                rebuild_api = first_round or bool(backend_issues)
                if rebuild_api:
                    self.on_event(f"  backend   {working(API, first_round, backend_issues)}")
                    api = self.backend.build(task, previous_api=api, issues=backend_issues)
                    self.on_event(f"  backend   done: {API}, {file_size(api)}")
                else:
                    self.on_event(f"  backend   no backend issues, keeping {API}")
                self.recorder.save_file(round_no, API, api, rebuilt=rebuild_api)

                # 2. Front end: runs when it has issues or api.py changed. After a review
                #    that asks for changes, one of the two is always true, so it runs every round.
                self.on_event(f"  frontend  {working(PAGE, first_round, frontend_issues)}")
                page = self.frontend.build(task, api, previous_page=page, issues=frontend_issues)
                self.on_event(f"  frontend  done: {PAGE}, {file_size(page)}")
                self.recorder.save_file(round_no, PAGE, page, rebuilt=True)

                # 3. Reviewer: the task and both files, nothing else.
                self.on_event(f"  reviewer  reviewing {API} and {PAGE}...")
                review = self.reviewer.review(task, api, page)
            except ModelCallError as error:
                return self._failed(round_no, error)
            self.recorder.save_review(round_no, review)

            # 4. Decide what happens next. Plain Python: no model is asked.
            if not review.readable:
                self.on_event("  warning   the reviewer's reply was not a valid verdict; counting it as changes requested")
            if review.approved:
                self.on_event(f"  reviewer  approved: {review.summary}")
                return self._finish(RunResult(APPROVED, round_no, api, page))
            self.on_event(f"  reviewer  changes requested ({count_by_owner(review.issues)}): {review.summary}")

        # The last round ended without approval.
        open_issues = review.issues or [Issue(owner=BOTH, text=review.summary)]
        for issue in open_issues:
            self.on_event(f"  open issue [{issue.owner}]: {issue.text}")
        return self._finish(RunResult(NOT_APPROVED, self.max_rounds, api, page, open_issues))

    def _failed(self, round_no: int, error: ModelCallError) -> RunResult:
        failure = f"{error.agent or 'model'} failed: {error.error_type}"
        self.on_event(f"  error     {failure}")
        return self._finish(RunResult(FAILED, round_no, failure=failure))

    def _finish(self, result: RunResult) -> RunResult:
        outcome = describe(result)
        final_files = None
        if result.final_api is not None and result.final_page is not None:
            final_files = {API: result.final_api, PAGE: result.final_page}
        self.recorder.finish(outcome, result.rounds, final_files, result.failure)
        self.on_event(f"Result: {outcome}. Run folder: {self.recorder.folder}")
        if final_files:
            self.on_event(f"Run the app:  cd {self.recorder.final_folder}")
            self.on_event("              python -m uvicorn api:app   (then open http://127.0.0.1:8000)")
        return result


def issues_for(review: Review | None, owner: str) -> list[str]:
    """The issues one builder must fix: those it owns plus those with no owner.

    A review that asks for changes but lists no issues gives its summary to both builders.
    """
    if review is None:
        return []
    if not review.issues:
        return [review.summary]
    return [issue.text for issue in review.issues if issue.owner in (owner, BOTH)]


def working(file: str, first_round: bool, issues: list[str]) -> str:
    """What a builder is doing, for the progress line."""
    if first_round:
        return f"writing {file}..."
    if issues:
        return f"fixing {plural(len(issues), 'issue')} in {file}..."
    return f"updating {file} for the new {API}..."


def count_by_owner(issues: list[Issue]) -> str:
    """For example "3 issues: 1 backend, 1 frontend, 1 for both"."""
    labels = {BACKEND: "backend", FRONTEND: "frontend", BOTH: "for both"}
    counts = []
    for owner, label in labels.items():
        n = sum(1 for issue in issues if issue.owner == owner)
        if n:
            counts.append(f"{n} {label}")
    total = plural(len(issues), "issue")
    return f"{total}: {', '.join(counts)}" if counts else total


def describe(result: RunResult) -> str:
    """The outcome in words, such as "approved after 2 rounds" or "failed in round 1"."""
    if result.outcome == FAILED:
        return f"failed in round {result.rounds}"
    return f"{result.outcome} after {plural(result.rounds, 'round')}"


def plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"
