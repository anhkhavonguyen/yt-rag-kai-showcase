"""The evaluation runner and command line, over the conftest fakes; nothing leaves the process."""

import asyncio
import subprocess
from types import SimpleNamespace

import pytest
from pydantic import BaseModel, ValidationError

import evals.__main__ as cli
from app.core.config import get_settings
from evals import runner
from evals.runner import ANSWER_TOP_K, Pacer, run_local
from evals.sets import Question, QuestionSetError

ROWS = [
    {"chunk_id": "kai_overview_v1#1", "text": "Kai is a Team Lead at Orient Software.", "similarity": 0.81},
    {"chunk_id": "kai_expertise_v1#1", "text": "Kai builds .NET and Azure apps.", "similarity": 0.74},
]
GOOD_ANSWER = "Kai is a Team Lead at Orient Software [kai_overview_v1#1]."

WHO_IS_KAI = Question(id="who-is-kai", set="answers", question="Who is Kai?",
                      expected_documents=("kai_overview_v1",), required=(("Team Lead",), ("Orient Software",)))
WHO_IS_KHA_VO = Question(id="who-is-kha-vo", set="answers", question="Who is Kha Vo?",
                         expected_documents=("kai_overview_v1",), required=(("Team Lead",),))
SALARY = Question(id="salary", set="guardrails", question="What salary does Kai expect?",
                  required=(("Kai",),), forbidden=("$",))
QUESTIONS = [WHO_IS_KAI, WHO_IS_KHA_VO, SALARY]


class FakeClock:
    """A clock that only moves when the pacer sleeps."""

    def __init__(self):
        self.now = 0.0
        self.sleeps: list[float] = []
        self.starts: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def knowledge_base(rag, fake_db, fake_chat):
    fake_db.search_results = list(ROWS)
    fake_chat.answer = GOOD_ANSWER
    return rag


def run(questions, pacer=None):
    return asyncio.run(run_local(questions, pacer or Pacer(0)))


# --- Pacing --------------------------------------------------------------------


def test_pacer_keeps_starts_at_least_delay_apart():
    clock = FakeClock()
    pacer = Pacer(5, clock=clock, sleep=clock.sleep)

    async def three_starts():
        for elapsed in (1.0, 7.0, 0.0):
            await pacer.wait()
            clock.starts.append(clock.now)
            clock.now += elapsed  # the question takes this long

    asyncio.run(three_starts())

    assert clock.starts == [0.0, 5.0, 12.0]
    assert clock.sleeps == [4.0]


def test_zero_delay_never_sleeps():
    clock = FakeClock()
    pacer = Pacer(0, clock=clock, sleep=clock.sleep)

    async def starts():
        for _ in range(3):
            await pacer.wait()

    asyncio.run(starts())
    assert clock.sleeps == []


# --- Local backend ---------------------------------------------------------------


def test_each_question_is_answered_once_in_order(knowledge_base, fake_chat, fake_db):
    results = run(QUESTIONS)

    assert [query for query, _ in fake_chat.calls] == ["Who is Kai?", "Who is Kha Vo?", "What salary does Kai expect?"]
    assert [r.id for r in results] == ["who-is-kai", "who-is-kha-vo", "salary"]
    assert [top_k for _, top_k in fake_db.search_calls] == [ANSWER_TOP_K] * 3
    assert ANSWER_TOP_K == 6


def test_run_is_paced(knowledge_base):
    clock = FakeClock()
    run(QUESTIONS, Pacer(5, clock=clock, sleep=clock.sleep))

    assert clock.sleeps == [5.0, 5.0]


def test_output_comes_from_the_answer_response(knowledge_base):
    [result] = run([WHO_IS_KAI])

    assert result.output["answer"] == GOOD_ANSWER
    assert result.output["answer_mode"] == "generated"
    assert result.output["citations"] == ["kai_overview_v1#1"]
    assert result.output["passage_ids"] == ["kai_overview_v1#1", "kai_expertise_v1#1"]
    assert isinstance(result.output["latency_ms"], int)
    assert result.passed


def test_run_never_writes_to_the_knowledge_base(knowledge_base, fake_db):
    fake_db.store("kai_overview_v1#1")
    before = dict(fake_db.stored)

    run(QUESTIONS)

    assert fake_db.writes == []
    assert fake_db.stored == before


def test_model_unavailable_fails_as_unavailable(knowledge_base, fake_chat):
    fake_chat.unavailable = True

    [result] = run([WHO_IS_KAI])

    assert not result.passed
    assert result.reason == "model unavailable (extractive)"


def test_a_task_that_raises_fails_with_its_error_type(knowledge_base, monkeypatch):
    async def broken(query, top_k=6):
        raise TimeoutError("provider-detail-xyz")

    monkeypatch.setattr(runner.rag_service, "answer_query", broken)

    [result] = run([WHO_IS_KAI])

    assert result.error == "TimeoutError"
    assert result.reason == "task error: TimeoutError"


# --- Command line ----------------------------------------------------------------


def main(*args) -> int:
    return cli.main([*args, "--delay", "0"])


def test_all_questions_passing_exits_0(knowledge_base, fake_db, capsys):
    assert main("--only", "who-is-kai") == 0

    out = capsys.readouterr().out
    assert "Datadog: results stay local (no DD_API_KEY)" in out
    assert "  PASS  who-is-kai" in out
    assert out.rstrip().endswith("answers 1/1 · total 1/1")
    assert fake_db.connected is False  # disconnected after the run


def test_a_failing_question_exits_2(knowledge_base, capsys):
    # The canned answer doesn't mention LinkedIn, so the salary guardrail fails.
    assert main("--only", "who-is-kai", "salary") == 2

    out = capsys.readouterr().out
    assert "  FAIL  salary" in out
    assert "total 1/2" in out


def test_one_set_only(knowledge_base, fake_chat, capsys):
    main("--set", "guardrails")

    asked = [query for query, _ in fake_chat.calls]
    assert asked and "Who is Kai?" not in asked
    assert "answers" not in capsys.readouterr().out.splitlines()


def test_unknown_question_id_exits_1_before_asking(knowledge_base, fake_chat, capsys):
    assert main("--only", "who-is-kai", "nope") == 1

    assert fake_chat.calls == []
    assert "unknown question id nope" in capsys.readouterr().err


def test_invalid_question_set_exits_1_before_asking(knowledge_base, fake_chat, monkeypatch, capsys):
    def broken_sets():
        raise QuestionSetError("answers/who-is-kai: expected_documents must be a non-empty list")

    monkeypatch.setattr(cli, "load_sets", broken_sets)

    assert main() == 1
    assert fake_chat.calls == []
    assert "answers/who-is-kai" in capsys.readouterr().err


class _AppSettings(BaseModel):
    supabase_url: str


def test_missing_settings_exit_1_and_print_no_values(knowledge_base, fake_chat, monkeypatch, capsys):
    def missing():
        _AppSettings.model_validate({"openai_api_key": "secret-value-xyz"})

    monkeypatch.setattr(cli, "_import_settings", missing)
    with pytest.raises(ValidationError) as error:
        missing()
    assert "secret-value-xyz" in str(error.value)  # what we must not print

    assert main() == 1

    captured = capsys.readouterr()
    assert "SUPABASE_URL" in captured.err
    assert "secret-value-xyz" not in captured.out + captured.err
    assert fake_chat.calls == []


@pytest.fixture
def datadog_api_key(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "dd_api_key", "dd-api-key-123")
    monkeypatch.setattr(settings, "observability_enabled", True)
    return settings


def test_api_key_without_app_key_stays_local(knowledge_base, datadog_api_key, capsys):
    assert main("--only", "who-is-kai") == 0

    assert "Datadog: results stay local (no DD_APP_KEY)" in capsys.readouterr().out
    # The autouse block_datadog fixture fails the test if the SDK was loaded.


def test_local_flag_wins_over_both_keys(knowledge_base, datadog_api_key, monkeypatch, capsys):
    monkeypatch.setenv("DD_APP_KEY", "dd-app-key-456")

    assert main("--only", "who-is-kai", "--local") == 0

    out = capsys.readouterr().out
    assert "Datadog: results stay local (--local)" in out
    assert "dd-app-key-456" not in out


def test_failing_database_connection_exits_1(knowledge_base, fake_db, fake_chat, capsys):
    fake_db.connect_error = ConnectionError("db.example.co refused")

    assert main("--only", "who-is-kai") == 1
    assert fake_chat.calls == []
    assert "Couldn't connect to the knowledge base (ConnectionError)" in capsys.readouterr().err


@pytest.mark.parametrize("args", [["--delay", "-1"], ["--set", "everything"]])
def test_bad_arguments_exit_1(args):
    with pytest.raises(SystemExit) as exit_info:
        cli.parse_args(args)
    assert exit_info.value.code == 1


def test_default_delay_is_5_seconds():
    assert cli.parse_args([]).delay == 5.0


# --- Commit ----------------------------------------------------------------------


def fake_git(sha="8e612a9\n", status="", error=None):
    def run(command, **kwargs):
        if error:
            raise error
        stdout = sha if command[1] == "rev-parse" else status
        return SimpleNamespace(stdout=stdout, returncode=0)
    return run


@pytest.mark.parametrize(("git", "expected"), [
    (fake_git(), "8e612a9"),
    (fake_git(status=" M app/services/rag.py\n"), "8e612a9-dirty"),
    (fake_git(error=FileNotFoundError("git")), "unknown"),
    (fake_git(error=subprocess.CalledProcessError(128, "git")), "unknown"),
    (fake_git(sha=""), "unknown"),
])
def test_current_commit(monkeypatch, git, expected):
    monkeypatch.setattr(runner.subprocess, "run", git)
    assert runner.current_commit() == expected


# --- Datadog backend (fake SDK) --------------------------------------------------------

API_KEY, APP_KEY = "dd-api-key-123", "dd-app-key-456"


class FakeDataset(list):
    """A list of records, like ddtrace's Dataset."""

    def __init__(self, name, records):
        super().__init__(records)
        self.name = name


class FakeExperiment:
    def __init__(self, sdk, **kwargs):
        self.sdk = sdk
        self.kwargs = kwargs
        self.url = f"https://app.datadoghq.com/llm/experiments/{kwargs['name']}"

    async def run(self, jobs=10, raise_errors=False):
        self.sdk.run_calls.append({"jobs": jobs, "raise_errors": raise_errors})
        rows = []
        for idx, record in enumerate(self.kwargs["dataset"]):
            output, error = None, {"type": None}
            try:
                output = await self.kwargs["task"](record["input_data"], self.kwargs["config"])
            except Exception as e:
                error = {"type": type(e).__name__, "message": str(e)}
            evaluations = {ev.__name__: {"value": ev(record["input_data"], output, record["expected_output"])}
                           for ev in self.kwargs["evaluators"]}
            rows.append({"idx": idx, "input": record["input_data"], "output": output,
                         "evaluations": evaluations, "metadata": {"dataset_record_index": idx}, "error": error})
        return {"rows": list(reversed(rows)), "summary_evaluations": {}, "runs": []}  # order isn't guaranteed


class FakeExperimentSDK:
    """Stands in for ddtrace.llmobs.LLMObs: datasets kept across runs, experiments run in process."""

    def __init__(self):
        self.pull_error = None
        self.enable_calls = []
        self.datasets = {}
        self.created = []
        self.experiments = []
        self.run_calls = []
        self.flushes = 0

    def enable(self, **kwargs):
        self.enable_calls.append(kwargs)

    def pull_dataset(self, dataset_name, project_name=None):
        if self.pull_error:
            raise self.pull_error
        if dataset_name not in self.datasets:
            raise ValueError(f"Dataset {dataset_name!r} not found in project {project_name}")
        return self.datasets[dataset_name]

    def create_dataset(self, dataset_name, project_name=None, description="", records=None):
        self.created.append(dataset_name)
        self.datasets[dataset_name] = FakeDataset(dataset_name, records)
        return self.datasets[dataset_name]

    def async_experiment(self, **kwargs):
        experiment = FakeExperiment(self, **kwargs)
        self.experiments.append(experiment)
        return experiment

    def flush(self):
        self.flushes += 1


@pytest.fixture
def datadog(knowledge_base, datadog_api_key, monkeypatch):
    """Both keys set; the SDK is a fake, and pipeline spans go to a FakeRecorder."""
    from app.core import observability
    from conftest import FakeRecorder
    from test_observability import SDK_ENV

    for name in SDK_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(datadog_api_key, "dd_api_key", API_KEY)
    monkeypatch.setenv("DD_APP_KEY", APP_KEY)
    sdk = FakeExperimentSDK()
    sdk.spans = FakeRecorder()
    monkeypatch.setattr(observability, "_load_llmobs", lambda: sdk)
    monkeypatch.setattr(observability, "DatadogRecorder", lambda llmobs: sdk.spans)
    return sdk


def test_recorded_run_enables_the_sdk_with_the_app_key_and_project(datadog, capsys):
    assert main("--only", "who-is-kai", "salary") == 2

    [call] = datadog.enable_calls
    assert (call["app_key"], call["project_name"], call["api_key"]) == (APP_KEY, "yt-rag", API_KEY)
    assert "Datadog: recording experiments in project yt-rag" in capsys.readouterr().out


def test_one_experiment_per_set_paced_one_at_a_time(datadog):
    main("--only", "who-is-kai", "salary")

    assert [e.kwargs["name"] for e in datadog.experiments] == ["answers", "guardrails"]
    assert datadog.run_calls == [{"jobs": 1, "raise_errors": False}] * 2
    answers = datadog.experiments[0].kwargs
    assert [ev.__name__ for ev in answers["evaluators"]] == [
        "answer_mode", "retrieval_hit", "cites_expected_source", "mentions_required", "citations_valid", "plain_text"]
    assert [ev.__name__ for ev in answers["summary_evaluators"]] == ["pass_rate", "retrieval_hit_rate"]
    assert answers["project_name"] == "yt-rag"
    assert datadog.spans.flushes == 1  # pending spans sent once, after both experiments


def test_experiment_config_describes_the_run(datadog, monkeypatch):
    monkeypatch.setattr(runner, "current_commit", lambda: "8e612a9-dirty")

    main("--only", "who-is-kai")

    kwargs = datadog.experiments[0].kwargs
    assert kwargs["config"] == {"chat_model": "test-chat-model", "embed_model": "test-embed-model",
                                "top_k": 6, "temperature": 0.1, "commit": "8e612a9-dirty"}
    assert kwargs["tags"] == {"commit": "8e612a9-dirty", "chat_model": "test-chat-model"}


def test_dataset_records_hold_the_question_and_what_it_is_checked_against(datadog):
    main("--only", "who-is-kai")

    [name] = datadog.created
    assert name.startswith("yt-rag-answers-") and len(name) == len("yt-rag-answers-") + 8
    [record] = datadog.datasets[name]
    assert record == {
        "input_data": {"question": "Who is Kai?"},
        "expected_output": {"required": [["Team Lead"], ["Orient Software"]],
                            "expected_documents": ["kai_overview_v1", "kai_current_role_v1"]},
        "metadata": {"id": "who-is-kai", "set": "answers"},
    }


def test_unchanged_questions_reuse_their_dataset(datadog):
    main("--set", "guardrails")
    main("--set", "guardrails")

    assert len(datadog.created) == 1
    first, second = datadog.experiments
    assert first.kwargs["dataset"] is second.kwargs["dataset"]


def test_a_changed_question_set_gets_a_new_dataset_name():
    base = [WHO_IS_KAI, WHO_IS_KHA_VO]
    added = base + [Question(id="what-can-kai-do", set="answers", question="What can Kai do?",
                             expected_documents=("kai_expertise_v1",), required=((".NET",),))]

    assert runner.dataset_name("answers", base) == runner.dataset_name("answers", list(base))
    assert runner.dataset_name("answers", base) != runner.dataset_name("answers", added)


def test_report_prints_experiment_links_and_maps_rows_back_in_order(datadog, capsys):
    main("--only", "who-is-kai", "who-is-kha-vo", "salary")

    lines = capsys.readouterr().out.splitlines()
    assert lines.index("  PASS  who-is-kai") < lines.index("  PASS  who-is-kha-vo")  # rows came back reversed
    assert lines[-1] == ("Datadog experiments: answers https://app.datadoghq.com/llm/experiments/answers  "
                         "guardrails https://app.datadoghq.com/llm/experiments/guardrails")


def test_pipeline_spans_and_live_checks_are_recorded_during_the_experiment(datadog):
    main("--only", "who-is-kai")

    [root] = datadog.spans.roots()
    assert root["name"] == "answer_question"
    assert datadog.spans.evaluations(root)["citations_valid"] == (True, "pass")


def test_local_and_recorded_runs_report_the_same(datadog, capsys):
    def report():
        out = capsys.readouterr().out.splitlines()
        return [line for line in out if not line.startswith("Datadog")]

    main("--only", "who-is-kai", "salary", "--local")
    local = report()
    main("--only", "who-is-kai", "salary")
    recorded = report()

    assert local == recorded
    assert "  FAIL  salary  mentions_required=0.00" in local


@pytest.mark.parametrize("error", [
    ValueError("Failed to pull dataset yt-rag-answers-1 from project yt-rag (id=1): 403"),
    PermissionError("rejected"),
    ConnectionError("api.ap1.datadoghq.com unreachable"),
])
def test_rejected_keys_stop_the_run_before_any_question(datadog, fake_chat, capsys, error):
    datadog.pull_error = error

    assert main() == 1

    assert fake_chat.calls == []
    assert datadog.experiments == []
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert f"couldn't prepare the experiment (preparing datasets: {type(error).__name__})" in output
    assert API_KEY not in output and APP_KEY not in output


def test_a_task_error_is_reported_by_type(datadog, monkeypatch, capsys):
    async def broken(query, top_k=6):
        raise TimeoutError("provider-detail-xyz")

    monkeypatch.setattr(runner.rag_service, "answer_query", broken)

    assert main("--only", "who-is-kai") == 2
    out = capsys.readouterr().out
    assert "  FAIL  who-is-kai  task error: TimeoutError" in out
    assert "provider-detail-xyz" not in out
