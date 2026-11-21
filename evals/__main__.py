"""Command line for the offline evaluation.

    python -m evals [--set answers|guardrails] [--only ID ...] [--local] [--delay SECONDS]

Needs the app's settings in .env (Gemini and Supabase keys) and a knowledge
base seeded with the default documents. With DD_API_KEY and DD_APP_KEY set, each
set run is also recorded as a Datadog experiment.

Exit status: 0 every question passed, 2 any question failed, 1 the run couldn't
start or stopped early.
"""

import argparse
import asyncio
import logging
import sys
from typing import List, Optional

from .sets import SET_NAMES, QuestionSetError, load_sets, select

EXIT_PASSED, EXIT_ERROR, EXIT_FAILED = 0, 1, 2
DEFAULT_DELAY_SECONDS = 5.0


class _Parser(argparse.ArgumentParser):
    """Bad arguments exit with 1 (couldn't start), not argparse's 2 (which means "failed" here)."""

    def error(self, message):
        self.print_usage(sys.stderr)
        print(f"{self.prog}: error: {message}", file=sys.stderr)
        sys.exit(EXIT_ERROR)


def _delay(value: str) -> float:
    seconds = float(value)
    if seconds < 0:
        raise argparse.ArgumentTypeError("must be 0 or more")
    return seconds


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = _Parser(prog="python -m evals", description="Evaluate the profile assistant's answers.")
    parser.add_argument("--set", dest="set_name", choices=SET_NAMES, help="run only this question set")
    parser.add_argument("--only", nargs="+", action="extend", metavar="ID",
                        help="run only these question IDs (from either set); overrides --set")
    parser.add_argument("--local", action="store_true", help="never send results to Datadog")
    parser.add_argument("--delay", type=_delay, default=DEFAULT_DELAY_SECONDS, metavar="SECONDS",
                        help=f"seconds between the start of each question (default {DEFAULT_DELAY_SECONDS:g})")
    return parser.parse_args(argv)


def _import_settings():
    """The app's settings. Separate so tests can simulate missing settings."""
    from app.core.config import get_settings

    return get_settings()


def load_app_settings():
    """The app's settings, or None after printing which ones are missing or invalid.

    Only field names are printed: pydantic's own message includes the input
    values, which can be secrets.
    """
    from pydantic import ValidationError

    try:
        return _import_settings()
    except ValidationError as e:
        names = sorted({".".join(str(part) for part in error["loc"]).upper() for error in e.errors()})
        print(f"Missing or invalid settings: {', '.join(names)}. Set them in .env (see .env.example).",
              file=sys.stderr)
        return None


def local_reason(local_flag: bool, settings, app_key: str) -> Optional[str]:
    """Why results stay local, or None when the run is recorded in Datadog."""
    if local_flag:
        return "--local"
    if not (settings.dd_api_key or "").strip():
        return "no DD_API_KEY"
    if not settings.observability_enabled:
        return "OBSERVABILITY_ENABLED=false"
    if not app_key:
        return "no DD_APP_KEY"
    return None


async def _run(questions, settings, app_key: str, reason: Optional[str], delay: float) -> int:
    from . import runner
    from .report import format_report

    pacer = runner.Pacer(delay)
    datadog = None
    if reason:
        print(f"Datadog: results stay local ({reason})")
    else:
        datadog = runner.DatadogRun(settings, app_key, pacer)
        try:
            datadog.prepare(questions)
        except Exception as e:
            print(f"Datadog: couldn't prepare the experiment ({datadog.step}: {type(e).__name__}). "
                  "Check DD_API_KEY, DD_APP_KEY and DD_SITE, or run with --local.", file=sys.stderr)
            return EXIT_ERROR
        print(f"Datadog: recording experiments in project {datadog.project_name}")

    try:
        await runner.connect_knowledge_base()
    except Exception as e:
        print(f"Couldn't connect to the knowledge base ({type(e).__name__}). Check the Supabase settings.",
              file=sys.stderr)
        return EXIT_ERROR

    print(f"Asking {len(questions)} questions, about {2 * len(questions)} model requests.")
    try:
        if datadog:
            results, links = await datadog.run()
        else:
            results, links = await runner.run_local(questions, pacer), None
    finally:
        await runner.disconnect_knowledge_base()

    print(format_report(results, links))
    return EXIT_PASSED if all(result.passed for result in results) else EXIT_FAILED


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    try:
        questions = select(load_sets(), args.set_name, args.only)
    except QuestionSetError as e:
        print(f"Question sets: {e}", file=sys.stderr)
        return EXIT_ERROR

    settings = load_app_settings()
    if settings is None:
        return EXIT_ERROR

    from .config import EvalSettings

    app_key = EvalSettings().dd_app_key.strip()
    reason = local_reason(args.local, settings, app_key)
    try:
        return asyncio.run(_run(questions, settings, app_key, reason, args.delay))
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return EXIT_ERROR
    except Exception as e:
        print(f"Evaluation stopped: {type(e).__name__}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
