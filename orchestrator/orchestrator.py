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

Every action is logged from the orchestrator's side by DispatchLog: what it sends
to which agent (->), what comes back (<-), how it routes issues and what it decides.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from .agents import (
    BACKEND,
    BOTH,
    FRONTEND,
    REVIEWER,
    BackendAgent,
    FrontendAgent,
    Issue,
    ProjectBuilderAgent,
    ProjectReviewerAgent,
    Review,
    ReviewerAgent,
    ReviewEntry,
)
from .llm import ModelCallError
from .project import Project, file_diff, line_counts
from .recorder import API, PAGE, RunRecorder, file_size

APPROVED = "approved"
NOT_APPROVED = "not approved"
FAILED = "failed"

# Exit status of `python -m orchestrator` for each outcome.
EXIT_CODES = {APPROVED: 0, NOT_APPROVED: 2, FAILED: 1}


class DispatchLog:
    """The orchestrator's log: one line per action, printed and saved to run.log.

    Every line starts with the time and "orchestrator", because the orchestrator is
    the one acting. For example:

        19:42:01 orchestrator  -> backend   write api.py | sends: task
        19:42:19 orchestrator  <- backend   api.py, 2.2 KB | 18.1 s
        19:43:20 orchestrator  route        backend: 0 issues | frontend: 1 issue
        19:43:20 orchestrator  decide       changes requested, round 1 of 3 -> round 2

    ASCII only: arrows such as "→" print as "?" on Windows code-page consoles.
    """

    LABEL_WIDTH = 13

    def __init__(
        self,
        on_event: Callable[[str], None],
        recorder: RunRecorder | None,
        clock: Callable[[], datetime] | None = None,
        timer: Callable[[], float] | None = None,
    ):
        self.on_event = on_event
        self.recorder = recorder  # None when there is no run folder, as for --apply
        self.clock = clock or datetime.now  # time of day for each line
        self.timer = timer or time.perf_counter  # measures how long each agent call took
        self._sent_at: float | None = None

    def line(self, label: str, text: str = "") -> None:
        line = f"{self.clock():%H:%M:%S} orchestrator  {label:<{self.LABEL_WIDTH}}{text}".rstrip()
        self.on_event(line)
        if self.recorder is not None:
            self.recorder.log_line(line)

    def round(self, round_no: int, max_rounds: int) -> None:
        self.line(f"== round {round_no} of {max_rounds} ==")

    def send(self, agent: str, job: str, sends: list[str]) -> None:
        """The orchestrator hands a job to an agent."""
        self._sent_at = self.timer()
        self.line(f"-> {agent}", f"{job} | sends: {', '.join(sends)}")

    def receive(self, agent: str, result: str) -> None:
        """The agent's result comes back to the orchestrator, with the call's duration."""
        elapsed = self.timer() - self._sent_at if self._sent_at is not None else 0.0
        self._sent_at = None
        self.line(f"<- {agent}", f"{result} | {elapsed:.1f} s")


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
        clock: Callable[[], datetime] | None = None,
        timer: Callable[[], float] | None = None,
    ):
        self.backend = backend
        self.frontend = frontend
        self.reviewer = reviewer
        self.recorder = recorder
        self.max_rounds = max_rounds
        self.log = DispatchLog(on_event, recorder, clock, timer)  # one line per orchestrator action

    def run(self, task: str) -> RunResult:
        log = self.log
        self.recorder.start(task, self.max_rounds)
        api: str | None = None  # the current api.py
        page: str | None = None  # the current index.html
        review: Review | None = None  # the latest review

        for round_no in range(1, self.max_rounds + 1):
            log.round(round_no, self.max_rounds)
            self.recorder.begin_round(round_no)
            first_round = review is None
            backend_issues = issues_for(review, BACKEND)
            frontend_issues = issues_for(review, FRONTEND)
            if not first_round:
                log.line("route", route_text(backend_issues, frontend_issues))
            try:
                # 1. Back end: always in round 1; afterwards only when it has issues to fix.
                rebuild_api = first_round or bool(backend_issues)
                if rebuild_api:
                    sends = ["task"] if first_round else ["task", API, plural(len(backend_issues), "issue")]
                    log.send(BACKEND, job(API, first_round, backend_issues), sends)
                    api = self.backend.build(task, previous_api=api, issues=backend_issues)
                    log.receive(BACKEND, f"{API}, {file_size(api)}")
                else:
                    log.line("skip", f"backend: no issues, keeping {API}")
                self.recorder.save_file(round_no, API, api, rebuilt=rebuild_api)

                # 2. Front end: runs when it has issues or api.py changed. After a review
                #    that asks for changes, one of the two is always true, so it runs every round.
                if first_round:
                    sends = ["task", API]
                elif frontend_issues:
                    sends = ["task", API, PAGE, plural(len(frontend_issues), "issue")]
                else:
                    sends = ["task", f"{API} (changed)", PAGE]
                log.send(FRONTEND, job(PAGE, first_round, frontend_issues), sends)
                page = self.frontend.build(task, api, previous_page=page, issues=frontend_issues)
                log.receive(FRONTEND, f"{PAGE}, {file_size(page)}")
                self.recorder.save_file(round_no, PAGE, page, rebuilt=True)

                # 3. Reviewer: the task and both files, nothing else.
                log.send(REVIEWER, f"review {API} and {PAGE}", ["task", API, PAGE])
                review = self.reviewer.review(task, api, page)
            except ModelCallError as error:
                return self._failed(round_no, error)
            log.receive(REVIEWER, verdict_text(review))
            self.recorder.save_review(round_no, review)

            # 4. Decide what happens next. Plain Python: no model is asked.
            if not review.readable:
                log.line("warning", "the reviewer's reply was not a valid verdict; counting it as changes requested")
            if review.approved:
                log.line("decide", "approved -> stop")
                return self._finish(RunResult(APPROVED, round_no, api, page))
            if round_no < self.max_rounds:
                log.line("decide", f"changes requested, round {round_no} of {self.max_rounds} -> round {round_no + 1}")

        # The last round ended without approval.
        log.line("decide", f"changes requested after the last round ({self.max_rounds}) -> stop")
        open_issues = review.issues or [Issue(owner=BOTH, text=review.summary)]
        for issue in open_issues:
            log.line("open issue", f"[{issue.owner}] {issue.text}")
        return self._finish(RunResult(NOT_APPROVED, self.max_rounds, api, page, open_issues))

    def _failed(self, round_no: int, error: ModelCallError) -> RunResult:
        agent = error.agent or "model"
        self.log.receive(agent, f"failed: {error.error_type}")
        self.log.line("decide", f"{agent} failed -> stop")
        failure = f"{agent} failed: {error.error_type}"
        return self._finish(RunResult(FAILED, round_no, failure=failure))

    def _finish(self, result: RunResult) -> RunResult:
        outcome = describe(result)
        final_files = None
        if result.final_api is not None and result.final_page is not None:
            final_files = {API: result.final_api, PAGE: result.final_page}
        self.recorder.finish(outcome, result.rounds, final_files, result.failure)
        self.log.line("result", f"{outcome} | folder: {self.recorder.folder}")
        if final_files:
            self.log.line("next", f"cd {self.recorder.final_folder}")
            self.log.line("next", "python -m uvicorn api:app   (then open http://127.0.0.1:8000)")
        return result


@dataclass
class ProjectRunResult:
    outcome: str  # APPROVED, NOT_APPROVED or FAILED
    rounds: int  # rounds started
    final_files: dict[str, str | None] | None = None  # path -> text (None: not created); None when failed
    open_issues: list[Issue] = field(default_factory=list)  # set when NOT_APPROVED
    failure: str | None = None  # set when FAILED


class ProjectOrchestrator:
    """The loop for project mode: the agents change files of an existing project.

    The same rounds and routing as app mode, with three differences. A builder with
    no --edit files of its type is never called. A builder may return no files. The
    reviewer sees each file with its diff against the project's original. Nothing is
    written to the project: the recorder saves every round's files in the run folder.
    """

    def __init__(
        self,
        project: Project,
        backend: ProjectBuilderAgent,
        frontend: ProjectBuilderAgent,
        reviewer: ProjectReviewerAgent,
        recorder: RunRecorder,
        max_rounds: int = 3,
        on_event: Callable[[str], None] = print,
        clock: Callable[[], datetime] | None = None,
        timer: Callable[[], float] | None = None,
    ):
        self.project = project
        self.builders = {BACKEND: backend, FRONTEND: frontend}
        self.reviewer = reviewer
        self.recorder = recorder
        self.max_rounds = max_rounds
        self.log = DispatchLog(on_event, recorder, clock, timer)

    def run(self, task: str) -> ProjectRunResult:
        log, project = self.log, self.project
        self.recorder.start_project(task, self.max_rounds, project)
        files: dict[str, str | None] = {f.path: f.original for f in project.edits}  # None: does not exist
        owned = {owner: project.paths_of(owner) for owner in (BACKEND, FRONTEND)}
        context_count = plural(len(project.context), "context file")
        log.line("project", f"{project.root} | {context_count}")
        for owner in (BACKEND, FRONTEND):
            log.line("files", f"{owner}: {', '.join(owned[owner]) or 'none, so it is never called'}")
        review: Review | None = None

        for round_no in range(1, self.max_rounds + 1):
            log.round(round_no, self.max_rounds)
            self.recorder.begin_round(round_no)
            first_round = review is None
            issues = {owner: issues_for(review, owner) for owner in (BACKEND, FRONTEND)}
            for owner, other in ((BACKEND, FRONTEND), (FRONTEND, BACKEND)):
                if not owned[owner] and review is not None:
                    # A side with no files can't fix anything: its issues go to the other side.
                    issues[other] = [i.text for i in review.issues] or [review.summary]
                    issues[owner] = []
            if not first_round:
                log.line("route", route_text(issues[BACKEND], issues[FRONTEND]))
            changed: dict[str, str] = {}  # path -> owner, this round
            rejected: list[tuple[str, str]] = []
            try:
                backend_changed = False
                for owner in (BACKEND, FRONTEND):
                    paths = owned[owner]
                    if not paths:
                        continue
                    follow = owner == FRONTEND and backend_changed and not first_round and not issues[owner]
                    if not (first_round or issues[owner] or follow):
                        log.line("skip", f"{owner}: no issues, keeping its files")
                        continue
                    own = {path: files[path] for path in paths}
                    backend_files = None
                    if owner == FRONTEND:
                        backend_files = {p: files[p] for p in owned[BACKEND] if files[p] is not None}
                    sends = ["task"] + ([context_count] if project.context else [])
                    sends.append(plural(len(paths), "own file"))
                    if backend_files:
                        sends.append(plural(len(backend_files), "back-end file") + " (read-only)")
                    if issues[owner]:
                        sends.append(plural(len(issues[owner]), "issue"))
                    log.send(owner, project_job(paths, first_round, issues[owner]), sends)
                    accepted, refused = self.builders[owner].build(
                        task, project.context, own, backend_files, issues[owner], backend_changed=follow
                    )
                    changes = {path: text for path, text in accepted.items() if text != files[path]}
                    log.receive(owner, change_summary(files, changes))
                    for path in refused:
                        log.line("warning", f"{owner} returned {path}, which is not in its --edit list: not saved")
                        rejected.append((owner, path))
                    files.update(changes)
                    changed.update({path: owner for path in changes})
                    if owner == BACKEND:
                        backend_changed = bool(changes)
                self.recorder.save_project_round(round_no, files, changed, rejected)

                entries = [
                    ReviewEntry(f.path, f.owner, files[f.path], file_diff(f.path, f.original, files[f.path]))
                    for f in project.edits
                ]
                differing = sum(1 for e in entries if e.diff)
                sends = ["task"] + ([context_count] if project.context else [])
                sends += [f"{differing} changed with diffs", f"{len(entries) - differing} unchanged"]
                log.send(REVIEWER, "review the changes", sends)
                review = self.reviewer.review(task, project.context, entries)
            except ModelCallError as error:
                return self._failed(round_no, error)
            log.receive(REVIEWER, verdict_text(review))
            self.recorder.save_review(round_no, review)

            if not review.readable:
                log.line("warning", "the reviewer's reply was not a valid verdict; counting it as changes requested")
            if review.approved:
                log.line("decide", "approved -> stop")
                return self._finish(ProjectRunResult(APPROVED, round_no, dict(files)))
            if round_no < self.max_rounds:
                log.line("decide", f"changes requested, round {round_no} of {self.max_rounds} -> round {round_no + 1}")

        log.line("decide", f"changes requested after the last round ({self.max_rounds}) -> stop")
        open_issues = review.issues or [Issue(owner=BOTH, text=review.summary)]
        for issue in open_issues:
            log.line("open issue", f"[{issue.owner}] {issue.text}")
        return self._finish(ProjectRunResult(NOT_APPROVED, self.max_rounds, dict(files), open_issues))

    def _failed(self, round_no: int, error: ModelCallError) -> ProjectRunResult:
        agent = error.agent or "model"
        self.log.receive(agent, f"failed: {error.error_type}")
        self.log.line("decide", f"{agent} failed -> stop")
        return self._finish(ProjectRunResult(FAILED, round_no, failure=f"{agent} failed: {error.error_type}"))

    def _finish(self, result: ProjectRunResult) -> ProjectRunResult:
        outcome = describe(result)
        self.recorder.finish_project(result.outcome, outcome, result.rounds, result.final_files, result.failure)
        folder = self.recorder.folder
        self.log.line("result", f"{outcome} | folder: {folder}")
        if result.outcome == APPROVED:
            self.log.line("next", f"read {folder / 'changes.diff'}")
            self.log.line("next", f"python -m orchestrator --apply {folder}")
        elif result.outcome == NOT_APPROVED:
            self.log.line("next", f"only approved runs can be applied; the last files are in {folder / 'final' / 'files'}")
        return result


def project_job(paths: list[str], first_round: bool, issues: list[str]) -> str:
    """What a project-mode builder is asked to do, for the dispatch line."""
    files = ", ".join(paths)
    if first_round:
        return f"edit {files}"
    if issues:
        return f"fix {plural(len(issues), 'issue')} in {files}"
    return f"follow the back-end changes in {files}"


def change_summary(before: dict[str, str | None], changes: dict[str, str]) -> str:
    """For example "changed app/main.py (+42 -7), created static/login.html (+80 -0)"."""
    if not changes:
        return "no changes"
    parts = []
    for path, text in changes.items():
        added, removed = line_counts(before[path], text)
        verb = "created" if before[path] is None else "changed"
        parts.append(f"{verb} {path} (+{added} -{removed})")
    return ", ".join(parts)


def issues_for(review: Review | None, owner: str) -> list[str]:
    """The issues one builder must fix: those it owns plus those with no owner.

    A review that asks for changes but lists no issues gives its summary to both builders.
    """
    if review is None:
        return []
    if not review.issues:
        return [review.summary]
    return [issue.text for issue in review.issues if issue.owner in (owner, BOTH)]


def job(file: str, first_round: bool, issues: list[str]) -> str:
    """What a builder is asked to do, for the dispatch line."""
    if first_round:
        return f"write {file}"
    if issues:
        return f"fix {plural(len(issues), 'issue')} in {file}"
    return f"update {file} for the new {API}"


def route_text(backend_issues: list[str], frontend_issues: list[str]) -> str:
    """For example "backend: 0 issues | frontend: 2 issues"."""
    return f"backend: {plural(len(backend_issues), 'issue')} | frontend: {plural(len(frontend_issues), 'issue')}"


def verdict_text(review: Review) -> str:
    """The reviewer's verdict for the return line."""
    if review.approved:
        return f"approved: {review.summary}"
    return f"changes requested ({count_by_owner(review.issues)}): {review.summary}"


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


def describe(result: RunResult | ProjectRunResult) -> str:
    """The outcome in words, such as "approved after 2 rounds" or "failed in round 1"."""
    if result.outcome == FAILED:
        return f"failed in round {result.rounds}"
    return f"{result.outcome} after {plural(result.rounds, 'round')}"


def plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"
