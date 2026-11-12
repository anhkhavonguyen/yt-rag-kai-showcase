"""Agent orchestrator: settings, model client, agents, routing loop, recorder and command line.

Everything runs offline. The agents get a FakeModelClient with scripted replies;
the real OpenAICompatibleClient only runs against an in-memory HTTP transport or
a stand-in SDK object, never the network.
"""

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

import orchestrator.__main__ as cli
from orchestrator.agents import (
    BACKEND_PROMPT,
    FRONTEND_PROMPT,
    REVIEWER_PROMPT,
    BackendAgent,
    FrontendAgent,
    Issue,
    Review,
    ReviewerAgent,
    extract_code,
    parse_review,
)
from orchestrator.config import DEFAULT_OPENAI_BASE_URL, MAX_RETRIES, TIMEOUT_SECONDS, OrchestratorSettings
from orchestrator.llm import ModelCallError, OpenAICompatibleClient
from orchestrator.orchestrator import Orchestrator
from orchestrator.recorder import RunRecorder, file_size

REPO_ROOT = Path(__file__).resolve().parents[1]
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
SECRET = "AIza-SECRET-KEY-123"
TASK = "a to-do list app"
FENCE = "```"
NOW = datetime(2026, 11, 12, 14, 30, 5)


class FakeModelClient:
    """Scripted stand-in for the model.

    Each call records its (system, user) prompt and returns the next scripted
    reply. A scripted exception is raised instead of returned.
    """

    def __init__(self, *replies):
        self.replies = list(replies)
        self.prompts: list[tuple[str, str]] = []

    def complete(self, system: str, user: str) -> str:
        self.prompts.append((system, user))
        if not self.replies:
            raise AssertionError("FakeModelClient has no scripted reply left")
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    @property
    def calls(self) -> int:
        return len(self.prompts)

    @property
    def roles(self) -> list[str]:
        """Which agent made each call, in order."""
        names = {BACKEND_PROMPT: "backend", FRONTEND_PROMPT: "frontend", REVIEWER_PROMPT: "reviewer"}
        return [names.get(system, "?") for system, _ in self.prompts]


class ProviderError(Exception):
    """Stands in for an SDK error such as openai.RateLimitError."""

    status_code = 429


def make_settings(**overrides) -> OrchestratorSettings:
    """Settings that never read a local .env."""
    values = {"openai_api_key": "test-key", "openai_base_url": "", "openai_chat_model": "test-model"}
    values.update(overrides)
    return OrchestratorSettings(_env_file=None, **values)


def stand_in_sdk(create):
    """An object shaped like openai.OpenAI for chat.completions.create only."""
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def completion(content):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def api_v(n: int) -> str:
    return f"from fastapi import FastAPI\n\napp = FastAPI()  # api v{n}"


def page_v(n: int) -> str:
    return f"<!doctype html>\n<html><body><h1>To-do v{n}</h1></body></html>"


def backend_reply(n: int) -> str:
    return f"Here is api.py:\n{FENCE}python\n{api_v(n)}\n{FENCE}\n"


def frontend_reply(n: int) -> str:
    return f"Here is the page:\n{FENCE}html\n{page_v(n)}\n{FENCE}\n"


def verdict(approved: bool, summary: str = "Summary.", issues=()) -> str:
    """A reviewer reply. `issues` is a list of (owner, text) pairs."""
    return json.dumps({
        "approved": approved,
        "summary": summary,
        "issues": [{"owner": owner, "issue": text} for owner, text in issues],
    })


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def file_names(folder: Path) -> list[str]:
    return sorted(str(p.relative_to(folder)).replace("\\", "/") for p in folder.rglob("*") if p.is_file())


# --- Settings -----------------------------------------------------------------


def test_settings_load_without_database_variables(monkeypatch):
    for name in ("SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_ROLE_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "gemini-key")
    monkeypatch.setenv("OPENAI_BASE_URL", GEMINI_URL)
    monkeypatch.setenv("OPENAI_CHAT_MODEL", "gemini-3.5-flash")

    settings = OrchestratorSettings(_env_file=None)

    assert settings.openai_api_key == "gemini-key"
    assert settings.base_url == GEMINI_URL
    assert settings.openai_chat_model == "gemini-3.5-flash"


def test_empty_or_unset_base_url_means_openai(monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "")
    assert OrchestratorSettings(_env_file=None).base_url == "https://api.openai.com/v1"

    monkeypatch.delenv("OPENAI_BASE_URL")
    assert OrchestratorSettings(_env_file=None).base_url == "https://api.openai.com/v1"


def test_settings_ignore_other_variables_in_env_file(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENAI_CHAT_MODEL", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "SUPABASE_URL=https://example.supabase.co\nSEED_TOKEN=abc\nOPENAI_CHAT_MODEL=from-env-file\n",
        encoding="utf-8",
    )

    assert OrchestratorSettings(_env_file=env_file).openai_chat_model == "from-env-file"


def test_package_imports_without_app_or_database_settings(tmp_path):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("SUPABASE_", "OPENAI_"))}
    env["PYTHONPATH"] = str(REPO_ROOT)
    code = (
        "import sys, orchestrator.__main__\n"
        "print(sorted(m for m in sys.modules if m == 'app' or m.startswith('app.')))"
    )

    # Run from an empty folder, so no .env is found either.
    out = subprocess.run(
        [sys.executable, "-c", code], cwd=tmp_path, env=env, capture_output=True, text=True, check=True
    )

    assert out.stdout.strip() == "[]"


# --- Model client ---------------------------------------------------------------


def test_client_sends_configured_url_key_and_model():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={
            "id": "chatcmpl-1", "object": "chat.completion", "created": 0, "model": "gemini-3.5-flash",
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": "hello"}}],
        })

    settings = make_settings(
        openai_api_key="gemini-key", openai_base_url=GEMINI_URL, openai_chat_model="gemini-3.5-flash"
    )
    client = OpenAICompatibleClient(settings, http_client=httpx.Client(transport=httpx.MockTransport(handler)))

    assert client.complete("system text", "user text") == "hello"

    (request,) = requests
    assert str(request.url) == GEMINI_URL + "chat/completions"
    assert request.headers["authorization"] == "Bearer gemini-key"
    body = json.loads(request.content)
    assert body["model"] == "gemini-3.5-flash"
    assert body["messages"] == [
        {"role": "system", "content": "system text"},
        {"role": "user", "content": "user text"},
    ]


def test_client_uses_timeout_retries_and_default_endpoint():
    client = OpenAICompatibleClient(make_settings())

    assert client.sdk.timeout == TIMEOUT_SECONDS
    assert client.sdk.max_retries == MAX_RETRIES
    assert str(client.sdk.base_url).rstrip("/") == DEFAULT_OPENAI_BASE_URL


def test_provider_error_keeps_only_type_and_status():
    client = OpenAICompatibleClient(make_settings())

    def create(**kwargs):
        raise ProviderError(f"Invalid API key {SECRET} for project 9876")

    client.sdk = stand_in_sdk(create)

    with pytest.raises(ModelCallError) as excinfo:
        client.complete("system", "user")

    error = excinfo.value
    assert error.error_type == "ProviderError (HTTP 429)"
    assert SECRET not in str(error)
    assert SECRET not in repr(error)
    assert error.__cause__ is None


@pytest.mark.parametrize("content", [None, "", "  \n "])
def test_empty_reply_is_a_model_call_error(content):
    client = OpenAICompatibleClient(make_settings())
    client.sdk = stand_in_sdk(lambda **kwargs: completion(content))

    with pytest.raises(ModelCallError) as excinfo:
        client.complete("system", "user")

    assert excinfo.value.error_type == "EmptyReply"


def test_fake_client_replays_script_and_records_prompts():
    client = FakeModelClient("first", ModelCallError("RateLimitError (HTTP 429)"))

    assert client.complete("sys", "one") == "first"
    with pytest.raises(ModelCallError):
        client.complete("sys", "two")
    with pytest.raises(AssertionError):
        client.complete("sys", "three")

    assert client.prompts == [("sys", "one"), ("sys", "two"), ("sys", "three")]


# --- Code extraction ---------------------------------------------------------------


def test_python_in_a_fence_is_kept_without_sentence_or_fence():
    assert extract_code(backend_reply(1) + "\nRun it with uvicorn.", "python") == api_v(1)


def test_py_tag_counts_as_python():
    assert extract_code(f"{FENCE}py\n{api_v(1)}\n{FENCE}", "python") == api_v(1)


def test_page_in_html_fence_is_kept_without_sentence_or_fence():
    assert extract_code(f"Here is your page.\n{FENCE}html\n{page_v(1)}\n{FENCE}\nEnjoy!", "html") == page_v(1)


def test_fence_for_the_language_is_preferred_over_other_fences():
    reply = f"{FENCE}bash\npip install fastapi\n{FENCE}\n{FENCE}python\n{api_v(1)}\n{FENCE}"

    assert extract_code(reply, "python") == api_v(1)


def test_first_fence_is_used_when_none_has_the_language():
    assert extract_code(f"{FENCE}\n{page_v(1)}\n{FENCE}", "html") == page_v(1)


@pytest.mark.parametrize("language, code", [("html", page_v(1)), ("python", api_v(1))])
def test_reply_without_fence_is_kept_whole_without_outer_whitespace(language, code):
    assert extract_code(f"\n  {code}  \n", language) == code


def test_cut_off_reply_keeps_the_code_after_the_opening_fence():
    assert extract_code(f"Sure!\n{FENCE}python\n{api_v(1)}", "python") == api_v(1)


@pytest.mark.parametrize("reply", ["   ", f"{FENCE}python\n{FENCE}", f"Here:\n{FENCE}html\n   \n{FENCE}"])
def test_reply_without_code_is_an_empty_code_failure(reply):
    with pytest.raises(ModelCallError) as excinfo:
        extract_code(reply, "python")

    assert excinfo.value.error_type == "EmptyCode"


# --- Back-end agent ---------------------------------------------------------------------


def test_backend_prompt_asks_for_one_fastapi_file_that_serves_the_page():
    for rule in ("```python", "FastAPI", "`app`", "in memory", "/api/", "GET /", "index.html", "__file__"):
        assert rule in BACKEND_PROMPT


def test_backend_round_one_gets_only_the_task():
    client = FakeModelClient(backend_reply(1))

    api = BackendAgent(client).build(TASK)

    assert api == api_v(1)
    assert client.prompts == [(BACKEND_PROMPT, f"Task: {TASK}")]


def test_backend_later_round_gets_task_previous_file_and_every_issue():
    client = FakeModelClient(backend_reply(2))

    api = BackendAgent(client).build(TASK, previous_api=api_v(1), issues=["Reject empty titles", "Return 404"])

    assert api == api_v(2)
    _, user = client.prompts[0]
    for part in (TASK, api_v(1), "- Reject empty titles", "- Return 404"):
        assert part in user


@pytest.mark.parametrize("reply", [ModelCallError("APITimeoutError"), "   "])
def test_backend_failure_or_empty_file_is_tagged_backend(reply):
    with pytest.raises(ModelCallError) as excinfo:
        BackendAgent(FakeModelClient(reply)).build(TASK)

    assert excinfo.value.agent == "backend"


# --- Front-end agent --------------------------------------------------------------------


def test_frontend_prompt_asks_for_one_page_that_calls_relative_api_urls():
    for rule in ("```html", "inline", "Load nothing external", "relative URLs", "/api/", "api.py"):
        assert rule in FRONTEND_PROMPT


def test_frontend_round_one_gets_the_task_and_the_api():
    client = FakeModelClient(frontend_reply(1))

    page = FrontendAgent(client).build(TASK, api_v(1))

    assert page == page_v(1)
    system, user = client.prompts[0]
    assert system == FRONTEND_PROMPT
    assert TASK in user and api_v(1) in user
    assert "previous index.html" not in user


def test_frontend_later_round_gets_previous_page_and_its_issues():
    client = FakeModelClient(frontend_reply(2))

    FrontendAgent(client).build(TASK, api_v(1), previous_page=page_v(1), issues=["Label the add button"])

    _, user = client.prompts[0]
    for part in (TASK, api_v(1), page_v(1), "- Label the add button"):
        assert part in user


def test_frontend_rebuild_without_issues_is_asked_to_follow_the_new_api():
    client = FakeModelClient(frontend_reply(2))

    FrontendAgent(client).build(TASK, api_v(2), previous_page=page_v(1), issues=[])

    _, user = client.prompts[0]
    assert api_v(2) in user and page_v(1) in user
    assert "api.py has changed" in user


@pytest.mark.parametrize("reply", [ModelCallError("APITimeoutError"), "   "])
def test_frontend_failure_or_empty_page_is_tagged_frontend(reply):
    with pytest.raises(ModelCallError) as excinfo:
        FrontendAgent(FakeModelClient(reply)).build(TASK, api_v(1))

    assert excinfo.value.agent == "frontend"


# --- Reviewer ---------------------------------------------------------------------------


def test_reviewer_gets_task_and_both_files_and_reads_an_approval():
    client = FakeModelClient(verdict(True, "Meets the task."))

    review = ReviewerAgent(client).review(TASK, api_v(1), page_v(1))

    assert review == Review(approved=True, summary="Meets the task.", issues=[])
    system, user = client.prompts[0]
    assert system == REVIEWER_PROMPT
    assert TASK in user and api_v(1) in user and page_v(1) in user


def test_reviewer_prompt_asks_for_owner_tagged_json():
    for rule in ('"owner": "backend"', '"issues"', "JSON only", "api.py", "index.html"):
        assert rule in REVIEWER_PROMPT


def test_verdict_with_backend_and_frontend_issues():
    review = parse_review(verdict(False, "Two fixes needed.", [
        ("backend", "POST /api/todos accepts an empty title"),
        ("frontend", "The add button has no label"),
    ]))

    assert review.approved is False
    assert review.summary == "Two fixes needed."
    assert review.issues == [
        Issue(owner="backend", text="POST /api/todos accepts an empty title"),
        Issue(owner="frontend", text="The add button has no label"),
    ]
    assert review.readable


def test_saved_verdict_keeps_owners_but_not_the_readable_flag():
    review = parse_review(verdict(False, "Fix.", [("frontend", "No label")]))

    assert review.model_dump() == {
        "approved": False, "summary": "Fix.", "issues": [{"owner": "frontend", "text": "No label"}],
    }


@pytest.mark.parametrize("owner, expected", [
    ("Back-end", "backend"), ("BACKEND", "backend"), ("front end", "frontend"), ("Front_End", "frontend"),
    ("design", "both"), ("", "both"), (None, "both"),
])
def test_owners_are_normalized(owner, expected):
    reply = json.dumps({"approved": False, "summary": "Fix.", "issues": [{"owner": owner, "issue": "Something"}]})

    assert parse_review(reply).issues == [Issue(owner=expected, text="Something")]


def test_plain_string_issues_go_to_both():
    reply = json.dumps({"approved": False, "summary": "Fix.", "issues": ["Something is off"]})

    assert parse_review(reply).issues == [Issue(owner="both", text="Something is off")]


def test_verdict_in_a_code_fence_is_read():
    review = parse_review(f"{FENCE}json\n{verdict(True, 'Good.')}\n{FENCE}")

    assert review.approved and review.summary == "Good." and review.readable


def test_verdict_with_text_around_it_is_read():
    review = parse_review(f"My review: {verdict(False, 'Fix it.', [('backend', 'No 404')])} Thanks!")

    assert review.issues == [Issue(owner="backend", text="No 404")] and review.readable


@pytest.mark.parametrize("reply", [
    "Looks mostly fine but the colors clash",
    '{"verdict": "ok"}',  # JSON, but not the verdict shape
])
def test_unreadable_reply_becomes_one_issue_for_both(reply):
    review = parse_review(reply)

    assert review.approved is False
    assert review.issues == [Issue(owner="both", text=reply)]
    assert review.readable is False


def test_failing_reviewer_call_is_tagged_reviewer():
    client = FakeModelClient(ModelCallError("RateLimitError (HTTP 429)"))

    with pytest.raises(ModelCallError) as excinfo:
        ReviewerAgent(client).review(TASK, api_v(1), page_v(1))

    assert excinfo.value.agent == "reviewer"


# --- Run recorder ---------------------------------------------------------------------


def test_runs_started_in_the_same_second_get_separate_folders(tmp_path):
    first = RunRecorder(tmp_path, now=NOW)
    second = RunRecorder(tmp_path, now=NOW)
    third = RunRecorder(tmp_path, now=NOW)

    assert [r.folder.name for r in (first, second, third)] == [
        "20261112-143005", "20261112-143005-2", "20261112-143005-3",
    ]

    first.save_file(1, "api.py", "first run", rebuilt=True)
    second.save_file(1, "api.py", "second run", rebuilt=True)
    assert read(first.folder / "round-1" / "api.py") == "first run"
    assert read(second.folder / "round-1" / "api.py") == "second run"


def test_round_files_are_written_as_soon_as_each_is_ready(tmp_path):
    recorder = RunRecorder(tmp_path, now=NOW)
    recorder.start(TASK, 3)

    recorder.save_file(1, "api.py", api_v(1), rebuilt=True)
    assert file_names(recorder.folder) == ["round-1/api.py"]

    recorder.save_file(1, "index.html", page_v(1), rebuilt=True)
    recorder.save_review(1, Review(approved=False, summary="Fix it.", issues=[Issue(owner="backend", text="No 404")]))
    assert file_names(recorder.folder) == ["round-1/api.py", "round-1/index.html", "round-1/review.json"]
    assert json.loads(read(recorder.folder / "round-1" / "review.json")) == {
        "approved": False, "summary": "Fix it.", "issues": [{"owner": "backend", "text": "No 404"}],
    }


def test_transcript_says_who_ran_and_lists_verdicts_with_owners(tmp_path):
    recorder = RunRecorder(tmp_path / "runs", now=NOW)
    recorder.start(TASK, 3)
    recorder.save_file(1, "api.py", api_v(1), rebuilt=True)
    recorder.save_file(1, "index.html", page_v(1), rebuilt=True)
    recorder.save_review(1, Review(approved=False, summary="One fix.",
                                   issues=[Issue(owner="frontend", text="Label the add button")]))
    recorder.save_file(2, "api.py", api_v(1), rebuilt=False)
    recorder.save_file(2, "index.html", page_v(2), rebuilt=True)
    recorder.save_review(2, Review(approved=True, summary="Meets the task."))

    recorder.finish("approved after 2 rounds", 2, {"api.py": api_v(1), "index.html": page_v(2)})

    transcript = read(recorder.folder / "transcript.md")
    for text in (
        f"- **Task:** {TASK}",
        "- **Outcome:** approved after 2 rounds",
        "## Round 1",
        f"- `api.py`: written by the back-end agent ({file_size(api_v(1))})",
        f"- `index.html`: written by the front-end agent ({file_size(page_v(1))})",
        "- Verdict: changes requested",
        "  - [frontend] Label the add button",
        "## Round 2",
        f"- `api.py`: kept from the previous round ({file_size(api_v(1))})",
        "- Verdict: approved",
        "`final/` holds `api.py` and `index.html` from round 2",
    ):
        assert text in transcript
    assert read(recorder.final_folder / "api.py") == api_v(1)
    assert read(recorder.final_folder / "index.html") == page_v(2)

    written = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert written
    assert all(recorder.folder in p.parents for p in written)


# --- Orchestrator: routing and stopping ----------------------------------------------------


def make_run(tmp_path, client, max_rounds=3):
    """An orchestrator whose three agents share `client`, with events collected in a list."""
    events: list[str] = []
    recorder = RunRecorder(tmp_path / "runs", now=NOW)
    orchestrator = Orchestrator(
        BackendAgent(client), FrontendAgent(client), ReviewerAgent(client), recorder,
        max_rounds=max_rounds, on_event=events.append,
    )
    return orchestrator, recorder, events


def test_round_one_runs_backend_then_frontend_then_reviewer(tmp_path):
    client = FakeModelClient(backend_reply(1), frontend_reply(1), verdict(True, "Meets the task."))
    orchestrator, recorder, _ = make_run(tmp_path, client)

    result = orchestrator.run(TASK)

    assert client.roles == ["backend", "frontend", "reviewer"]
    assert client.prompts[0][1] == f"Task: {TASK}"  # the back-end agent receives the task
    assert api_v(1) in client.prompts[1][1]  # the front-end agent receives the new api.py
    assert api_v(1) in client.prompts[2][1] and page_v(1) in client.prompts[2][1]
    assert (result.outcome, result.rounds) == ("approved", 1)
    assert (result.final_api, result.final_page) == (api_v(1), page_v(1))
    assert file_names(recorder.folder) == [
        "final/api.py", "final/index.html",
        "round-1/api.py", "round-1/index.html", "round-1/review.json",
        "transcript.md",
    ]


def test_only_frontend_issues_skip_the_backend_and_keep_api(tmp_path):
    client = FakeModelClient(
        backend_reply(1), frontend_reply(1), verdict(False, "One fix.", [("frontend", "The add button has no label")]),
        frontend_reply(2), verdict(True, "Meets the task."),
    )
    orchestrator, recorder, events = make_run(tmp_path, client)

    result = orchestrator.run(TASK)

    assert client.roles == ["backend", "frontend", "reviewer", "frontend", "reviewer"]
    frontend_round_2 = client.prompts[3][1]
    for part in (TASK, api_v(1), page_v(1), "- The add button has no label"):
        assert part in frontend_round_2
    assert "  backend   no backend issues, keeping api.py" in events
    assert read(recorder.folder / "round-2" / "api.py") == api_v(1)
    assert (result.final_api, result.final_page) == (api_v(1), page_v(2))


def test_backend_issue_rebuilds_api_then_the_page_for_the_new_api(tmp_path):
    client = FakeModelClient(
        backend_reply(1), frontend_reply(1),
        verdict(False, "One fix.", [("backend", "POST /api/todos accepts an empty title")]),
        backend_reply(2), frontend_reply(2), verdict(True, "Meets the task."),
    )
    orchestrator, recorder, events = make_run(tmp_path, client)

    result = orchestrator.run(TASK)

    assert client.roles == ["backend", "frontend", "reviewer", "backend", "frontend", "reviewer"]
    backend_round_2 = client.prompts[3][1]
    for part in (TASK, api_v(1), "- POST /api/todos accepts an empty title"):
        assert part in backend_round_2
    frontend_round_2 = client.prompts[4][1]
    assert api_v(2) in frontend_round_2 and page_v(1) in frontend_round_2
    assert "POST /api/todos accepts an empty title" not in frontend_round_2
    assert "api.py has changed" in frontend_round_2
    assert "  frontend  updating index.html for the new api.py..." in events

    # Approved in round 2: no round 3, and the final app is round 2's files.
    assert (result.outcome, result.rounds) == ("approved", 2)
    for name in ("api.py", "index.html"):
        assert read(recorder.final_folder / name) == read(recorder.folder / "round-2" / name)
    assert (result.final_api, result.final_page) == (api_v(2), page_v(2))


def test_issue_without_owner_goes_to_both_agents(tmp_path):
    client = FakeModelClient(
        backend_reply(1), frontend_reply(1), verdict(False, "One fix.", [("design", "Use the word 'task' everywhere")]),
        backend_reply(2), frontend_reply(2), verdict(True, "Good."),
    )
    orchestrator, _, _ = make_run(tmp_path, client)

    orchestrator.run(TASK)

    assert client.roles[3:5] == ["backend", "frontend"]
    assert "Use the word 'task' everywhere" in client.prompts[3][1]
    assert "Use the word 'task' everywhere" in client.prompts[4][1]


def test_review_without_issues_sends_its_summary_to_both_agents(tmp_path):
    client = FakeModelClient(
        backend_reply(1), frontend_reply(1), verdict(False, "Nothing saves."),
        backend_reply(2), frontend_reply(2), verdict(True, "Good."),
    )
    orchestrator, _, _ = make_run(tmp_path, client)

    orchestrator.run(TASK)

    assert "- Nothing saves." in client.prompts[3][1]
    assert "- Nothing saves." in client.prompts[4][1]


def test_unreadable_verdict_warns_and_sends_the_reply_to_both_agents(tmp_path):
    client = FakeModelClient(
        backend_reply(1), frontend_reply(1), "Looks mostly fine but the colors clash",
        backend_reply(2), frontend_reply(2), verdict(True, "Good."),
    )
    orchestrator, _, events = make_run(tmp_path, client)

    result = orchestrator.run(TASK)

    assert (result.outcome, result.rounds) == ("approved", 2)
    assert any(e.startswith("  warning ") and "not a valid verdict" in e for e in events)
    assert "Looks mostly fine but the colors clash" in client.prompts[3][1]
    assert "Looks mostly fine but the colors clash" in client.prompts[4][1]


def test_never_approved_stops_at_the_round_limit_after_nine_calls(tmp_path):
    replies = []
    for n in (1, 2, 3):
        replies += [backend_reply(n), frontend_reply(n), verdict(False, f"Round {n} problems.",
                                                                 [("backend", f"Issue from round {n}")])]
    client = FakeModelClient(*replies)
    orchestrator, recorder, events = make_run(tmp_path, client, max_rounds=3)

    result = orchestrator.run(TASK)

    assert client.calls == 9
    assert (result.outcome, result.rounds) == ("not approved", 3)
    assert (result.final_api, result.final_page) == (api_v(3), page_v(3))
    assert result.open_issues == [Issue(owner="backend", text="Issue from round 3")]
    assert "  open issue [backend]: Issue from round 3" in events
    assert f"Result: not approved after 3 rounds. Run folder: {recorder.folder}" in events
    assert read(recorder.final_folder / "api.py") == api_v(3)


# --- Orchestrator: progress lines and failures ---------------------------------------------


def test_events_for_a_one_round_approved_run(tmp_path):
    client = FakeModelClient(backend_reply(1), frontend_reply(1), verdict(True, "Meets the task."))
    orchestrator, recorder, events = make_run(tmp_path, client)

    orchestrator.run(TASK)

    assert events == [
        "== Round 1 of 3 ==",
        "  backend   writing api.py...",
        f"  backend   done: api.py, {file_size(api_v(1))}",
        "  frontend  writing index.html...",
        f"  frontend  done: index.html, {file_size(page_v(1))}",
        "  reviewer  reviewing api.py and index.html...",
        "  reviewer  approved: Meets the task.",
        f"Result: approved after 1 round. Run folder: {recorder.folder}",
        f"Run the app:  cd {recorder.final_folder}",
        "              python -m uvicorn api:app   (then open http://127.0.0.1:8000)",
    ]


def test_events_count_issues_per_owner_and_name_the_fixes(tmp_path):
    client = FakeModelClient(
        backend_reply(1), frontend_reply(1),
        verdict(False, "Three fixes.", [("backend", "A"), ("frontend", "B"), ("design", "C")]),
        backend_reply(2), frontend_reply(2), verdict(True, "Good."),
    )
    orchestrator, _, events = make_run(tmp_path, client)

    orchestrator.run(TASK)

    assert "  reviewer  changes requested (3 issues: 1 backend, 1 frontend, 1 for both): Three fixes." in events
    assert "  backend   fixing 2 issues in api.py..." in events  # its own plus the unowned one
    assert "  frontend  fixing 2 issues in index.html..." in events


def test_reviewer_failure_stops_the_run_and_keeps_finished_files(tmp_path):
    client = FakeModelClient(backend_reply(1), frontend_reply(1), ModelCallError("RateLimitError (HTTP 429)"))
    orchestrator, recorder, events = make_run(tmp_path, client)

    result = orchestrator.run(TASK)

    assert client.calls == 3
    assert (result.outcome, result.rounds, result.final_api) == ("failed", 1, None)
    assert result.failure == "reviewer failed: RateLimitError (HTTP 429)"
    assert "  error     reviewer failed: RateLimitError (HTTP 429)" in events
    assert events[-1] == f"Result: failed in round 1. Run folder: {recorder.folder}"
    assert file_names(recorder.folder) == ["round-1/api.py", "round-1/index.html", "transcript.md"]
    transcript = read(recorder.folder / "transcript.md")
    assert "- **Outcome:** failed in round 1" in transcript
    assert "- **Failure:** reviewer failed: RateLimitError (HTTP 429)" in transcript


@pytest.mark.parametrize("replies, failure, files", [
    ((ModelCallError("APITimeoutError"),), "backend failed: APITimeoutError", ["transcript.md"]),
    ((backend_reply(1), "   "), "frontend failed: EmptyCode", ["round-1/api.py", "transcript.md"]),
])
def test_builder_failures_name_the_agent(tmp_path, replies, failure, files):
    orchestrator, recorder, _ = make_run(tmp_path, FakeModelClient(*replies))

    result = orchestrator.run(TASK)

    assert (result.outcome, result.failure) == ("failed", failure)
    assert file_names(recorder.folder) == files


def test_provider_message_with_the_key_reaches_no_output_or_file(tmp_path):
    """End to end through the real client, whose provider error message holds the key."""
    client = OpenAICompatibleClient(make_settings())
    scripted = [backend_reply(1), frontend_reply(1)]

    def create(**kwargs):
        if scripted:
            return completion(scripted.pop(0))
        raise ProviderError(f"Invalid API key {SECRET} for project 9876")

    client.sdk = stand_in_sdk(create)
    orchestrator, recorder, events = make_run(tmp_path, client)

    result = orchestrator.run(TASK)

    assert result.failure == "reviewer failed: ProviderError (HTTP 429)"
    assert not [e for e in events if SECRET in e]
    for path in recorder.folder.rglob("*"):
        if path.is_file():
            assert SECRET not in read(path)


# --- Command line ----------------------------------------------------------------------


@pytest.fixture(autouse=True)
def no_real_model_client(monkeypatch):
    """The command line must never build the real client in tests."""

    def forbidden(settings):
        raise AssertionError("Test tried to build the real model client")

    monkeypatch.setattr(cli, "build_client", forbidden)


@pytest.fixture
def scripted_client(monkeypatch):
    """Make the command line use a FakeModelClient with the given replies."""

    def install(*replies) -> FakeModelClient:
        client = FakeModelClient(*replies)
        monkeypatch.setattr(cli, "build_client", lambda settings: client)
        return client

    return install


def test_defaults():
    args = cli.parse_args([TASK])

    assert (args.task, args.max_rounds, args.out_dir) == (TASK, 3, "orchestrator_runs")


@pytest.mark.parametrize("argv, message", [
    ([], "a task is required"),
    (["   "], "a task is required"),
    ([TASK, "--max-rounds", "0"], "--max-rounds must be between 1 and 10 (got 0)"),
    ([TASK, "--max-rounds", "11"], "--max-rounds must be between 1 and 10 (got 11)"),
])
def test_invalid_input_exits_1_before_any_model_call(tmp_path, capsys, scripted_client, argv, message):
    client = scripted_client()
    out_dir = tmp_path / "runs"

    status = cli.main(argv + ["--out-dir", str(out_dir)], settings=make_settings())

    assert status == 1
    assert message in capsys.readouterr().err
    assert client.calls == 0
    assert not out_dir.exists()


def test_missing_api_key_exits_1_before_any_model_call(monkeypatch, tmp_path, capsys, scripted_client):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    client = scripted_client()

    status = cli.main([TASK, "--out-dir", str(tmp_path)], settings=OrchestratorSettings(_env_file=None))

    assert status == 1
    assert "OPENAI_API_KEY is required" in capsys.readouterr().err
    assert client.calls == 0


def test_max_rounds_that_is_not_a_number_exits_1(capsys):
    with pytest.raises(SystemExit) as excinfo:
        cli.main([TASK, "--max-rounds", "many"], settings=make_settings())

    assert excinfo.value.code == 1


@pytest.mark.parametrize("replies, max_rounds, status, result_line", [
    ((backend_reply(1), frontend_reply(1), verdict(True, "Good.")), "3", 0,
     "Result: approved after 1 round."),
    ((backend_reply(1), frontend_reply(1), verdict(False, "Fix it.", [("frontend", "No label")])), "1", 2,
     "Result: not approved after 1 round."),
    ((ModelCallError("RateLimitError (HTTP 429)"),), "3", 1,
     "Result: failed in round 1."),
])
def test_exit_status_matches_the_outcome(tmp_path, capsys, scripted_client, replies, max_rounds, status, result_line):
    client = scripted_client(*replies)

    assert cli.main([TASK, "--max-rounds", max_rounds, "--out-dir", str(tmp_path)], settings=make_settings()) == status

    out = capsys.readouterr().out
    assert f"== Round 1 of {max_rounds} ==" in out
    assert result_line in out
    assert client.roles[0] == "backend"


def test_progress_lines_survive_a_console_that_cannot_show_them(monkeypatch):
    written = []
    monkeypatch.setattr(sys, "stdout", SimpleNamespace(encoding="cp1252", write=written.append, flush=lambda: None))

    cli.print_line("  reviewer  approved: ✔ looks good ▸")

    assert "".join(written) == "  reviewer  approved: ? looks good ?\n"
