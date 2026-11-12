"""Command line for the agent orchestrator.

    python -m orchestrator "a to-do list app"
    python -m orchestrator "a counter app" --max-rounds 1
    python -m orchestrator --task-file my-task.md

Project mode (the agents change files of this project):

    python -m orchestrator --task-file task.md --edit app/main.py --edit static/chat.html \\
        --context tests/test_api.py
    python -m orchestrator --apply orchestrator_runs/<run>

Exit status: 0 approved (or applied), 2 not approved after the last round, 1 bad
input, a failed model call, or an apply that was refused or whose tests failed.
"""

import argparse
import subprocess
import sys
from pathlib import Path

from .agents import (
    BACKEND,
    FRONTEND,
    REVIEWER,
    BackendAgent,
    FrontendAgent,
    ProjectBuilderAgent,
    ProjectReviewerAgent,
    ReviewerAgent,
)
from .config import PROJECT_TIMEOUT_SECONDS, TIMEOUT_SECONDS, OrchestratorSettings
from .handoff import HandoffChannel
from .llm import ModelClient, OpenAICompatibleClient
from .orchestrator import EXIT_CODES, DispatchLog, Orchestrator, ProjectOrchestrator
from .project import Project, ProjectError, apply_run, load_project
from .recorder import RecordingClient, RunRecorder

MIN_ROUNDS, MAX_ROUNDS = 1, 10


class _Parser(argparse.ArgumentParser):
    """Exits with status 1 on bad arguments. argparse's usual 2 means "not approved" here."""

    def error(self, message: str):
        self.print_usage(sys.stderr)
        self.exit(1, f"{self.prog}: error: {message}\n")


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = _Parser(
        prog="python -m orchestrator",
        description=(
            "Build a small web app (a FastAPI back end and a page that calls it) "
            "with a back-end agent, a front-end agent and a reviewer agent. "
            "With --edit, the agents change files of this project instead (project mode)."
        ),
    )
    parser.add_argument(
        "task", nargs="?", default="",
        help='what to build, for example "a to-do list app"',
    )
    parser.add_argument(
        "--task-file", default=None, metavar="PATH",
        help="read the task from this UTF-8 file instead of the command line",
    )
    parser.add_argument(
        "--max-rounds", type=int, default=3,
        help=f"most build-review rounds, {MIN_ROUNDS} to {MAX_ROUNDS} (default 3)",
    )
    parser.add_argument(
        "--out-dir", default="orchestrator_runs",
        help="folder that holds the run folders (default orchestrator_runs)",
    )
    parser.add_argument(
        "--edit", action="append", default=[], metavar="PATH",
        help="project mode: a project file the agents may change or create; .py goes to the back-end "
             "agent, .html, .css and .js to the front-end agent; repeat for each file (at most 8)",
    )
    parser.add_argument(
        "--context", action="append", default=[], metavar="PATH",
        help="project mode: a read-only file every agent receives, such as a test file; repeatable",
    )
    parser.add_argument(
        "--handoff", action="store_true",
        help="call no model API: write each agent call to <run folder>/handoff/NN-<agent>.request.md "
             "and wait for NN-<agent>.reply.md, written by another agent or a person "
             "(no OPENAI_API_KEY needed)",
    )
    parser.add_argument(
        "--apply", default=None, metavar="RUN_FOLDER",
        help="copy an approved project-mode run's files into the project, then run the tests; "
             "the files are restored if the tests fail",
    )
    return parser.parse_args(argv)


def read_task(args: argparse.Namespace) -> tuple[str, str | None]:
    """The task text, and why it can't be used (or None). Reads --task-file when given."""
    if args.task_file is None:
        return args.task.strip(), None
    if args.task.strip():
        return "", "pass the task as an argument or with --task-file, not both"
    try:
        return Path(args.task_file).read_text(encoding="utf-8").strip(), None
    except (OSError, UnicodeDecodeError):
        return "", f"can't read the task file {args.task_file} (it must exist and be UTF-8 text)"


def input_problem(task: str, args: argparse.Namespace, settings: OrchestratorSettings) -> str | None:
    """Why the run can't start, or None. Checked before any model call."""
    if not task:
        return 'a task is required, for example: python -m orchestrator "a counter app"'
    if not MIN_ROUNDS <= args.max_rounds <= MAX_ROUNDS:
        return f"--max-rounds must be between {MIN_ROUNDS} and {MAX_ROUNDS} (got {args.max_rounds})"
    if not settings.openai_api_key and not args.handoff:
        return "OPENAI_API_KEY is required. Set it in .env; a free Gemini key works (see orchestrator/README.md)."
    return None


def load_project_files(args: argparse.Namespace) -> tuple[Project | None, str | None]:
    """The project for project mode (None in app mode), and why it can't be used (or None)."""
    if not args.edit:
        if args.context:
            return None, "--context needs at least one --edit (project mode)"
        return None, None
    try:
        return load_project(Path.cwd(), args.edit, args.context, Path(args.out_dir)), None
    except ProjectError as error:
        return None, str(error)


def build_client(settings: OrchestratorSettings, timeout: float = TIMEOUT_SECONDS) -> ModelClient:
    """The real model client. Tests replace this function with a scripted fake."""
    return OpenAICompatibleClient(settings, timeout=timeout)


def _recorded(client: ModelClient | HandoffChannel, recorder: RunRecorder, agent: str) -> RecordingClient:
    """The client one agent uses, saving every call. A hand-off channel gives each agent its own named files."""
    if isinstance(client, HandoffChannel):
        client = client.for_agent(agent)
    return RecordingClient(client, recorder, agent)


def build_agents(client: ModelClient | HandoffChannel, recorder: RunRecorder) -> tuple[BackendAgent, FrontendAgent, ReviewerAgent]:
    """The three agents, sharing one client. Each call is saved to the run folder under the agent's name."""
    return (
        BackendAgent(_recorded(client, recorder, BACKEND)),
        FrontendAgent(_recorded(client, recorder, FRONTEND)),
        ReviewerAgent(_recorded(client, recorder, REVIEWER)),
    )


def build_project_agents(
    client: ModelClient | HandoffChannel, recorder: RunRecorder
) -> tuple[ProjectBuilderAgent, ProjectBuilderAgent, ProjectReviewerAgent]:
    """The project-mode agents, sharing one client, with every call saved like build_agents."""
    return (
        ProjectBuilderAgent(BACKEND, _recorded(client, recorder, BACKEND)),
        ProjectBuilderAgent(FRONTEND, _recorded(client, recorder, FRONTEND)),
        ProjectReviewerAgent(_recorded(client, recorder, REVIEWER)),
    )


def run_project_tests(root: Path) -> int:
    """Run the project's offline tests for --apply, showing their output. Tests replace this function."""
    return subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=root).returncode


def print_line(line: str) -> None:
    """Print one progress line. Characters the console can't show (on a Windows
    code page, for example) become "?" instead of crashing the run."""
    encoding = sys.stdout.encoding or "utf-8"
    print(line.encode(encoding, errors="replace").decode(encoding), flush=True)


def apply(args: argparse.Namespace) -> int:
    """`--apply RUN_FOLDER`: copy an approved project-mode run into the project, keep it if the tests pass."""
    if args.task.strip() or args.task_file or args.edit or args.context:
        print("error: --apply takes only the run folder (no task, --task-file, --edit or --context)", file=sys.stderr)
        return 1
    root = Path.cwd()
    log = DispatchLog(print_line, None)
    try:
        return apply_run(Path(args.apply), root, lambda: run_project_tests(root), log.line)
    except ProjectError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


def main(argv: list[str] | None = None, settings: OrchestratorSettings | None = None) -> int:
    args = parse_args(argv)
    if args.apply is not None:
        return apply(args)  # needs no model and no settings
    if settings is None:
        settings = OrchestratorSettings()  # reads OPENAI_* from the environment and .env
    task, problem = read_task(args)
    problem = problem or input_problem(task, args, settings)
    project = None
    if not problem:
        project, problem = load_project_files(args)
    if problem:
        print(f"error: {problem}", file=sys.stderr)
        return 1

    recorder = RunRecorder(args.out_dir)
    if args.handoff:
        # No model API: every agent call becomes a request file, answered by a reply file.
        client = HandoffChannel(recorder.folder / "handoff")
        source = f"hand-off: requests and replies in {client.folder}"
    else:
        # One client, shared by all three agents. Project-mode replies are longer, so they get more time.
        client = build_client(settings, timeout=PROJECT_TIMEOUT_SECONDS if project else TIMEOUT_SECONDS)
        source = f"{settings.openai_chat_model} at {settings.base_url}"
    if project is None:
        backend, frontend, reviewer = build_agents(client, recorder)
        orchestrator = Orchestrator(
            backend=backend,
            frontend=frontend,
            reviewer=reviewer,
            recorder=recorder,
            max_rounds=args.max_rounds,
            on_event=print_line,  # every line shows the orchestrator sending to or hearing from an agent
        )
    else:
        backend, frontend, reviewer = build_project_agents(client, recorder)
        orchestrator = ProjectOrchestrator(
            project=project,
            backend=backend,
            frontend=frontend,
            reviewer=reviewer,
            recorder=recorder,
            max_rounds=args.max_rounds,
            on_event=print_line,
        )
    orchestrator.log.line("model", source)  # where the agents' answers come from
    result = orchestrator.run(task)
    return EXIT_CODES[result.outcome]


if __name__ == "__main__":
    sys.exit(main())
