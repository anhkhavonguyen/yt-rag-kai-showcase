"""
Runs selected questions through the local RAG pipeline and scores the answers.

Two backends share one task and one set of evaluators:
- `run_local`: a plain loop; nothing is sent to Datadog.
- `DatadogRun` (see below): each set becomes a Datadog experiment.

Both ask one question at a time, paced for the model's free tier, and only
read the knowledge base.
"""

import asyncio
import subprocess
import time
from typing import Any, Callable, Dict, List, Optional

from app.core import observability
from app.models.requests import AnswerRequest
from app.services.rag import rag_service

from .checks import EVALUATORS, SUMMARY_EVALUATORS, QuestionResult, score
from .sets import Question, by_set, content_hash

# The same default as /answer, so an evaluation sees what a visitor would.
ANSWER_TOP_K: int = AnswerRequest.model_fields["top_k"].default


class Pacer:
    """Keeps at least `delay` seconds between the start of one question and the next."""

    def __init__(self, delay: float, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], Any] = asyncio.sleep):
        self.delay = max(0.0, delay)
        self._clock = clock
        self._sleep = sleep
        self._last_start: Optional[float] = None

    async def wait(self) -> None:
        if self.delay and self._last_start is not None:
            remaining = self._last_start + self.delay - self._clock()
            if remaining > 0:
                await self._sleep(remaining)
        self._last_start = self._clock()


def current_commit() -> str:
    """The checked-out commit, e.g. "8e612a9", with "-dirty" for uncommitted changes; "unknown" without git."""
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                             check=True, timeout=10).stdout.strip()
        status = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True,
                                check=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    if not sha:
        return "unknown"
    return f"{sha}-dirty" if status.strip() else sha


async def connect_knowledge_base() -> None:
    """Connect the database the pipeline searches. The run only ever reads from it."""
    await rag_service.db.connect()


async def disconnect_knowledge_base() -> None:
    try:
        await rag_service.db.disconnect()
    except Exception:
        pass  # nothing to clean up that matters for the report


def make_task(pacer: Pacer):
    """The task for one question: wait for pacing, answer it as /answer would, return the output."""

    async def ask_assistant(input_data: Dict[str, Any], config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        await pacer.wait()
        response = await rag_service.answer_query(input_data["question"], top_k=ANSWER_TOP_K)
        debug = response["debug"]
        return {
            "answer": response["text"],
            "answer_mode": debug["answer_mode"],
            "citations": list(response["citations"]),
            "passage_ids": list(debug["top_doc_ids"]),
            "latency_ms": debug["latency_ms"],
        }

    return ask_assistant


async def run_local(questions: List[Question], pacer: Pacer) -> List[QuestionResult]:
    """Ask each question in order and score its answer. Sends nothing to Datadog."""
    task = make_task(pacer)
    results = []
    for question in questions:
        output: Optional[Dict[str, Any]] = None
        error: Optional[str] = None
        try:
            output = await task({"question": question.question})
        except Exception as e:  # answer_query handles provider errors; this is a safety net
            error = type(e).__name__
        results.append(QuestionResult(question.id, question.set, output, score(question, output), error))
    return results


class DatadogRun:
    """Records each set run as a Datadog experiment.

    `prepare` enables the SDK and pulls or creates every dataset before any
    question is asked, so a rejected key or an unreachable Datadog costs no
    model requests. `step` names what was being done, for error messages.
    """

    def __init__(self, settings, app_key: str, pacer: Pacer):
        self._settings = settings
        self._app_key = app_key
        self._pacer = pacer
        self.project_name = (settings.dd_llmobs_ml_app or "").strip() or "yt-rag"
        self.step = "starting"
        self._llmobs: Any = None
        self._plan: List[tuple] = []  # (set name, its questions, its dataset)

    def prepare(self, questions: List[Question]) -> None:
        self.step = "starting the Datadog SDK"
        if not observability.setup(self._settings, app_key=self._app_key, project_name=self.project_name):
            raise RuntimeError("Datadog tracing did not start")
        self._llmobs = observability.sdk()

        self.step = "preparing datasets"
        self._plan = [
            (set_name, group, self._dataset(dataset_name(set_name, group), group))
            for set_name, group in by_set(questions).items()
        ]

    def _dataset(self, name: str, questions: List[Question]):
        """The dataset for exactly these questions: reused when it exists, created otherwise."""
        try:
            return self._llmobs.pull_dataset(dataset_name=name, project_name=self.project_name)
        except ValueError as e:
            if "not found" not in str(e):
                raise
        return self._llmobs.create_dataset(
            dataset_name=name,
            project_name=self.project_name,
            description="Questions for python -m evals (evals/questions/). Named by a hash of their content.",
            records=[
                {"input_data": {"question": q.question}, "expected_output": q.expected_output(),
                 "metadata": {"id": q.id, "set": q.set}}
                for q in questions
            ],
        )

    def _config(self) -> Dict[str, Any]:
        settings = self._settings
        chat_model = settings.anthropic_chat_model if settings.ai_provider == "anthropic" else settings.openai_chat_model
        return {
            "chat_model": chat_model,
            "embed_model": settings.openai_embed_model,
            "top_k": ANSWER_TOP_K,
            "temperature": settings.temperature,
            "commit": current_commit(),
        }

    async def run(self):
        """Run each prepared set as an experiment. Returns the results and each experiment's link."""
        config = self._config()
        tags = {"commit": str(config["commit"]), "chat_model": str(config["chat_model"])}
        task = make_task(self._pacer)
        results: List[QuestionResult] = []
        links: Dict[str, str] = {}
        for set_name, questions, dataset in self._plan:
            self.step = f"running the {set_name} experiment"
            experiment = self._llmobs.async_experiment(
                name=set_name,
                task=task,
                dataset=dataset,
                evaluators=EVALUATORS[set_name],
                summary_evaluators=SUMMARY_EVALUATORS[set_name],
                description=f"python -m evals: the {set_name} question set",
                project_name=self.project_name,
                config=config,
                tags=tags,
            )
            # One question at a time: the SDK's default of 10 would ignore pacing.
            outcome = await experiment.run(jobs=1, raise_errors=False)
            results.extend(_results_from_rows(questions, dataset, outcome["rows"]))
            links[set_name] = experiment.url
        observability.flush()
        return results, links


def dataset_name(set_name: str, questions: List[Question]) -> str:
    """yt-rag-<set>-<first 8 hex digits of the questions' content hash>."""
    return f"yt-rag-{set_name}-{content_hash(questions)[:8]}"


def _results_from_rows(questions: List[Question], dataset, rows) -> List[QuestionResult]:
    """Experiment rows back to questions, in set order.

    A row's `idx` points at its dataset record, whose metadata holds the
    question ID. The answer is scored here with the same evaluators Datadog
    ran, so local and recorded runs report identically.
    """
    by_id = {}
    for row in rows:
        try:
            record = dataset[row["idx"]]
            question_id = (record.get("metadata") or {}).get("id")
        except (IndexError, KeyError, TypeError):
            question_id = None
        if question_id:
            by_id[question_id] = row

    results = []
    for question in questions:
        row = by_id.get(question.id)
        if row is None:
            results.append(QuestionResult(question.id, question.set, None, score(question, None), "NoResult"))
            continue
        error = (row.get("error") or {}).get("type") or None
        output = row.get("output") if not error else None
        results.append(QuestionResult(question.id, question.set, output, score(question, output), error))
    return results
