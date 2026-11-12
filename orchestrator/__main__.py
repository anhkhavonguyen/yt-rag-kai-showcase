"""Command line for the agent orchestrator.

    python -m orchestrator "a to-do list app"
    python -m orchestrator "a counter app" --max-rounds 1

Exit status: 0 approved, 2 not approved after the last round, 1 bad input or a
failed model call.
"""

import argparse
import sys

from .agents import BackendAgent, FrontendAgent, ReviewerAgent
from .config import OrchestratorSettings
from .llm import ModelClient, OpenAICompatibleClient
from .orchestrator import EXIT_CODES, Orchestrator
from .recorder import RunRecorder

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
            "with a back-end agent, a front-end agent and a reviewer agent."
        ),
    )
    parser.add_argument(
        "task", nargs="?", default="",
        help='what to build, for example "a to-do list app"',
    )
    parser.add_argument(
        "--max-rounds", type=int, default=3,
        help=f"most build-review rounds, {MIN_ROUNDS} to {MAX_ROUNDS} (default 3)",
    )
    parser.add_argument(
        "--out-dir", default="orchestrator_runs",
        help="folder that holds the run folders (default orchestrator_runs)",
    )
    return parser.parse_args(argv)


def input_problem(args: argparse.Namespace, settings: OrchestratorSettings) -> str | None:
    """Why the run can't start, or None. Checked before any model call."""
    if not args.task.strip():
        return 'a task is required, for example: python -m orchestrator "a counter app"'
    if not MIN_ROUNDS <= args.max_rounds <= MAX_ROUNDS:
        return f"--max-rounds must be between {MIN_ROUNDS} and {MAX_ROUNDS} (got {args.max_rounds})"
    if not settings.openai_api_key:
        return "OPENAI_API_KEY is required. Set it in .env; a free Gemini key works (see orchestrator/README.md)."
    return None


def build_client(settings: OrchestratorSettings) -> ModelClient:
    """The real model client. Tests replace this function with a scripted fake."""
    return OpenAICompatibleClient(settings)


def print_line(line: str) -> None:
    """Print one progress line. Characters the console can't show (on a Windows
    code page, for example) become "?" instead of crashing the run."""
    encoding = sys.stdout.encoding or "utf-8"
    print(line.encode(encoding, errors="replace").decode(encoding), flush=True)


def main(argv: list[str] | None = None, settings: OrchestratorSettings | None = None) -> int:
    args = parse_args(argv)
    if settings is None:
        settings = OrchestratorSettings()  # reads OPENAI_* from the environment and .env
    problem = input_problem(args, settings)
    if problem:
        print(f"error: {problem}", file=sys.stderr)
        return 1

    client = build_client(settings)  # one client, shared by all three agents
    orchestrator = Orchestrator(
        backend=BackendAgent(client),
        frontend=FrontendAgent(client),
        reviewer=ReviewerAgent(client),
        recorder=RunRecorder(args.out_dir),
        max_rounds=args.max_rounds,
        on_event=print_line,  # this is how you see which agent is working
    )
    result = orchestrator.run(args.task.strip())
    return EXIT_CODES[result.outcome]


if __name__ == "__main__":
    sys.exit(main())
