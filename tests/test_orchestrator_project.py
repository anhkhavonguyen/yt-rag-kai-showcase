"""Agent orchestrator, project mode: path checks, multi-file replies, the project loop,
the run folder, the command line and --apply.

Everything runs offline in temporary project folders. The agents get a scripted fake
model; --apply gets a fake test runner, so no test ever runs pytest inside pytest.
"""

import json
import os
from datetime import datetime
from pathlib import Path

import pytest

import orchestrator.__main__ as cli
from orchestrator.agents import (
    PROJECT_BACKEND_PROMPT,
    PROJECT_FRONTEND_PROMPT,
    PROJECT_REVIEWER_PROMPT,
    ProjectBuilderAgent,
    ReviewEntry,
    parse_files,
    project_builder_message,
    project_reviewer_message,
)
from orchestrator.config import OrchestratorSettings
from orchestrator.llm import ModelCallError
from orchestrator.orchestrator import ProjectOrchestrator
from orchestrator.project import ProjectError, apply_run, load_project, sha256
from orchestrator.recorder import RunRecorder

NOW = datetime(2026, 11, 12, 14, 30, 5)
TASK = "Make the chat page dark and add a sign-in route."
FENCE = "```"
RUNS = Path("orchestrator_runs")

API_V0 = "from fastapi import FastAPI\n\napp = FastAPI()\n"
PAGE_V0 = "<!doctype html>\n<p>light</p>\n"
TEST_TEXT = "def test_sign_in():\n    assert True\n"


class FakeModelClient:
    """Scripted stand-in for the model: records each (system, user) prompt and returns the next reply."""

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
    def roles(self) -> list[str]:
        names = {PROJECT_BACKEND_PROMPT: "backend", PROJECT_FRONTEND_PROMPT: "frontend",
                 PROJECT_REVIEWER_PROMPT: "reviewer"}
        return [names.get(system, "?") for system, _ in self.prompts]


class FakeTimer:
    def __init__(self):
        self.now = 0.0

    def __call__(self) -> float:
        self.now += 1.5
        return self.now


def line(label: str, text: str = "") -> str:
    return f"{NOW:%H:%M:%S} orchestrator  {label:<13}{text}".rstrip()


def files_reply(files: dict[str, str], intro: str = "Here are the files.") -> str:
    """A builder reply holding each file as a FILE: block."""
    blocks = [f"FILE: {path}\n{FENCE}\n{text}{FENCE}" for path, text in files.items()]
    return intro + "\n\n" + "\n\n".join(blocks) + "\n"


def verdict(approved: bool, summary: str = "Summary.", issues=()) -> str:
    return json.dumps({
        "approved": approved, "summary": summary,
        "issues": [{"owner": owner, "issue": text} for owner, text in issues],
    })


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def file_names(folder: Path) -> list[str]:
    return sorted(str(p.relative_to(folder)).replace("\\", "/") for p in folder.rglob("*") if p.is_file())


@pytest.fixture
def project_dir(tmp_path, monkeypatch):
    """A small project: app/main.py, static/chat.html and a test file, as the current folder."""
    root = tmp_path / "project"
    (root / "app").mkdir(parents=True)
    (root / "static").mkdir()
    (root / "tests").mkdir()
    (root / "app" / "main.py").write_bytes(API_V0.encode())
    (root / "static" / "chat.html").write_bytes(PAGE_V0.encode())
    (root / "tests" / "test_sign_in.py").write_bytes(TEST_TEXT.encode())
    monkeypatch.chdir(root)
    return root


def make_project(root, edits=("app/main.py", "static/chat.html"), context=("tests/test_sign_in.py",)):
    return load_project(root, list(edits), list(context), RUNS)


def make_run(root, client, edits=("app/main.py", "static/chat.html"), context=("tests/test_sign_in.py",),
             max_rounds=3):
    events: list[str] = []
    recorder = RunRecorder(root / RUNS, now=NOW)
    backend, frontend, reviewer = cli.build_project_agents(client, recorder)
    orchestrator = ProjectOrchestrator(
        make_project(root, edits, context), backend, frontend, reviewer, recorder,
        max_rounds=max_rounds, on_event=events.append, clock=lambda: NOW, timer=FakeTimer(),
    )
    return orchestrator, recorder, events


# --- Paths: --edit and --context (orchestrator/project.py) --------------------------------


def test_owners_come_from_file_types(project_dir):
    (project_dir / "static" / "theme.css").write_text("body {}\n", encoding="utf-8")

    project = load_project(project_dir, ["app/main.py", "static/chat.html", "static/theme.css"], [], RUNS)

    assert [(f.path, f.owner) for f in project.edits] == [
        ("app/main.py", "backend"), ("static/chat.html", "frontend"), ("static/theme.css", "frontend"),
    ]
    assert project.edits[0].original == API_V0
    assert project.edits[0].sha256 == sha256(API_V0.encode())


def test_a_new_file_in_an_existing_folder_may_be_created(project_dir):
    project = load_project(project_dir, ["static/admin-login.html"], [], RUNS)

    (new,) = project.edits
    assert (new.path, new.owner, new.original, new.sha256) == ("static/admin-login.html", "frontend", None, None)


def test_crlf_files_are_read_with_newlines(project_dir):
    (project_dir / "static" / "chat.html").write_bytes(b"<p>a</p>\r\n<p>b</p>\r\n")

    (page,) = load_project(project_dir, ["static/chat.html"], [], RUNS).edits

    assert page.original == "<p>a</p>\n<p>b</p>\n"
    assert page.sha256 == sha256(b"<p>a</p>\r\n<p>b</p>\r\n")


@pytest.mark.parametrize("make_path, message", [
    (lambda root: str(root / "app" / "main.py"), "use a path relative to the project folder"),
    (lambda root: "../outside.py", "is outside the project folder"),
    (lambda root: "app/../../outside.py", "is outside the project folder"),
    (lambda root: ".git/hooks.py", "is inside .git/"),
    (lambda root: "orchestrator_runs/page.html", "is inside the run output folder"),
    (lambda root: ".env", ".env files are not allowed"),
    (lambda root: "app/.env.production", ".env files are not allowed"),
    (lambda root: "notes.txt", "has an unsupported file type"),
    (lambda root: "missing/page.html", "is in a folder that does not exist"),
    (lambda root: "app/big.py", "is larger than 200 KB"),
])
def test_rejected_edit_paths(project_dir, make_path, message):
    (project_dir / ".git").mkdir()
    (project_dir / "app" / "big.py").write_text("#" * (200 * 1024 + 1), encoding="utf-8")

    with pytest.raises(ProjectError) as excinfo:
        load_project(project_dir, [make_path(project_dir)], [], RUNS)

    assert message in str(excinfo.value)


def test_an_edit_path_given_twice_is_rejected(project_dir):
    with pytest.raises(ProjectError, match="is given twice"):
        load_project(project_dir, ["app/main.py", "./app/main.py"], [], RUNS)


def test_more_than_eight_edit_paths_are_rejected(project_dir):
    paths = [f"static/page{n}.html" for n in range(9)]

    with pytest.raises(ProjectError, match=r"at most 8 --edit paths are allowed \(got 9\)"):
        load_project(project_dir, paths, [], RUNS)


def test_a_link_that_leaves_the_project_is_rejected(project_dir, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        os.symlink(outside, project_dir / "linked", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("this system does not allow creating symbolic links")

    with pytest.raises(ProjectError, match="is outside the project folder"):
        load_project(project_dir, ["linked/page.html"], [], RUNS)


def test_context_files_are_read(project_dir):
    project = load_project(project_dir, ["app/main.py"], ["tests/test_sign_in.py"], RUNS)

    assert project.context == [("tests/test_sign_in.py", TEST_TEXT)]


@pytest.mark.parametrize("context, message", [
    ("tests/missing.py", "does not exist"),
    ("app/main.py", "is also given with --edit"),
    (".env", ".env files are not allowed"),
    ("../outside.py", "is outside the project folder"),
    ("tests/big.txt", "is larger than 200 KB"),
])
def test_rejected_context_paths(project_dir, context, message):
    (project_dir / ".env").write_text("OPENAI_API_KEY=secret\n", encoding="utf-8")
    (project_dir / "tests" / "big.txt").write_text("x" * (200 * 1024 + 1), encoding="utf-8")

    with pytest.raises(ProjectError) as excinfo:
        load_project(project_dir, ["app/main.py"], [context], RUNS)

    assert message in str(excinfo.value)


# --- Replies with files, and what the agents are sent (orchestrator/agents.py) ------------------


def test_two_files_are_read_whole():
    reply = files_reply({"static/chat.html": "<p>dark</p>\n", "static/theme.css": ":root { --bg: #000000; }\n"})

    assert parse_files(reply) == {"static/chat.html": "<p>dark</p>\n", "static/theme.css": ":root { --bg: #000000; }\n"}


def test_a_fence_inside_a_file_does_not_cut_it_short():
    text = 'HELP = """\nRun it:\n```bash\npython -m app\n```\n"""\n'
    reply = f"FILE: app/help.py\n{FENCE}python\n{text}{FENCE}\n\nFILE: app/main.py\n{FENCE}python\n{API_V0}{FENCE}\n"

    assert parse_files(reply) == {"app/help.py": text, "app/main.py": API_V0}


@pytest.mark.parametrize("label", [
    "### FILE: app/main.py", "**FILE:** app/main.py", "**FILE: app/main.py**", "FILE: `app/main.py`",
    "FILE: ./app/main.py",
])
def test_label_forms(label):
    assert parse_files(f"{label}\n{FENCE}python\n{API_V0}{FENCE}") == {"app/main.py": API_V0}


def test_a_reply_without_labels_holds_no_files():
    assert parse_files("No changes.") == {}


def test_a_cut_off_file_is_a_truncated_reply():
    reply = f"FILE: static/chat.html\n{FENCE}html\n<p>dark</p>\n\nFILE: static/theme.css\n{FENCE}css\n:root {{"

    with pytest.raises(ModelCallError) as excinfo:
        parse_files(reply)

    assert excinfo.value.error_type == "TruncatedReply"


@pytest.mark.parametrize("reply, error_type", [
    ("FILE: app/main.py\nThe whole file is unchanged.", "MalformedReply"),
    (f"FILE: app/main.py\n{FENCE}python\n   \n{FENCE}", "EmptyCode"),
])
def test_a_label_without_code_is_a_model_failure(reply, error_type):
    with pytest.raises(ModelCallError) as excinfo:
        parse_files(reply)

    assert excinfo.value.error_type == error_type


def test_a_builder_returns_files_outside_its_list_as_rejected():
    client = FakeModelClient(files_reply({"app/main.py": "app = 1\n", "static/chat.html": "<p>x</p>\n"}))

    accepted, rejected = ProjectBuilderAgent("backend", client).build(TASK, [], {"app/main.py": API_V0})

    assert accepted == {"app/main.py": "app = 1\n"}
    assert rejected == ["static/chat.html"]


def test_builder_failures_are_tagged_with_the_agent():
    client = FakeModelClient(f"FILE: static/chat.html\n{FENCE}html\n<p>cut")

    with pytest.raises(ModelCallError) as excinfo:
        ProjectBuilderAgent("frontend", client).build(TASK, [], {"static/chat.html": PAGE_V0})

    assert (excinfo.value.agent, excinfo.value.error_type) == ("frontend", "TruncatedReply")


def test_builder_message_lists_its_inputs():
    message = project_builder_message(
        TASK, [("tests/test_sign_in.py", TEST_TEXT)],
        own={"static/chat.html": PAGE_V0, "static/admin-login.html": None},
        backend_files={"app/main.py": API_V0},
        issues=["Label the token field"],
    )

    for part in (
        f"Task:\n{TASK}",
        "Context files (read-only; do not return them)", "tests/test_sign_in.py:", TEST_TEXT.rstrip(),
        "The back-end files (read-only; call only what they define)", "app/main.py:", API_V0.rstrip(),
        "Your files (return only those you change, each complete)", "static/chat.html:", PAGE_V0.rstrip(),
        "static/admin-login.html: does not exist yet; create it if the task needs it.",
        "- Label the token field",
    ):
        assert part in message


def test_builder_message_asks_to_follow_back_end_changes():
    message = project_builder_message(TASK, [], {"static/chat.html": PAGE_V0}, {"app/main.py": API_V0},
                                      backend_changed=True)

    assert "The back-end files changed this round" in message


def test_reviewer_message_has_each_changed_file_with_its_diff_and_notes_the_rest():
    entries = [
        ReviewEntry("app/main.py", "backend", API_V0, ""),
        ReviewEntry("static/chat.html", "frontend", "<p>dark</p>\n", "--- a/static/chat.html\n+++ b/static/chat.html\n"),
        ReviewEntry("static/admin-login.html", "frontend", None, ""),
    ]

    message = project_reviewer_message(TASK, [("tests/test_sign_in.py", TEST_TEXT)], entries)

    for part in (
        f"Task:\n{TASK}", "tests/test_sign_in.py:",
        "### app/main.py (owner: backend): unchanged",
        "### static/chat.html (owner: frontend): changed", "<p>dark</p>", "--- a/static/chat.html",
        "### static/admin-login.html (owner: frontend): does not exist, and was not created",
    ):
        assert part in message
    assert API_V0.rstrip() not in message  # an unchanged file is only noted


# --- The project loop (orchestrator/orchestrator.py) -------------------------------------


def test_round_one_inputs_and_an_approved_run_folder(project_dir):
    api_v1 = API_V0 + "\n@app.post('/admin/login')\ndef login():\n    return None\n"
    page_v1 = "<!doctype html>\n<p>dark</p>\n"
    client = FakeModelClient(
        files_reply({"app/main.py": api_v1}), files_reply({"static/chat.html": page_v1}), verdict(True, "Done."),
    )
    orchestrator, recorder, events = make_run(project_dir, client)

    result = orchestrator.run(TASK)

    assert client.roles == ["backend", "frontend", "reviewer"]
    backend_message, frontend_message, reviewer_message = (user for _, user in client.prompts)
    assert TASK in backend_message and TEST_TEXT.rstrip() in backend_message and API_V0.rstrip() in backend_message
    assert PAGE_V0.rstrip() not in backend_message
    # The front end gets the back end as the back-end agent left it, read-only.
    assert "The back-end files (read-only" in frontend_message and api_v1.rstrip() in frontend_message
    assert PAGE_V0.rstrip() in frontend_message and TEST_TEXT.rstrip() in frontend_message
    assert "+@app.post('/admin/login')" in reviewer_message and "+<p>dark</p>" in reviewer_message

    assert (result.outcome, result.rounds) == ("approved", 1)
    assert result.final_files == {"app/main.py": api_v1, "static/chat.html": page_v1}
    assert file_names(recorder.folder) == [
        "changes.diff",
        "final/files/app/main.py", "final/files/static/chat.html",
        "manifest.json",
        "round-1/calls/01-backend.md", "round-1/calls/02-frontend.md", "round-1/calls/03-reviewer.md",
        "round-1/files/app/main.py", "round-1/files/static/chat.html",
        "round-1/review.json", "run.log", "transcript.md",
    ]
    diff = read(recorder.folder / "changes.diff")
    assert "--- a/app/main.py\n+++ b/app/main.py\n" in diff and "+<p>dark</p>\n-<p>light</p>\n" not in diff
    assert "-<p>light</p>\n+<p>dark</p>\n" in diff
    manifest = json.loads(read(recorder.folder / "manifest.json"))
    assert manifest["mode"] == "project" and manifest["outcome"] == "approved" and manifest["task"] == TASK
    assert manifest["project"] == str(project_dir.resolve())
    assert manifest["files"] == [
        {"path": "app/main.py", "owner": "backend", "existed": True, "sha256": sha256(API_V0.encode())},
        {"path": "static/chat.html", "owner": "frontend", "existed": True, "sha256": sha256(PAGE_V0.encode())},
    ]
    assert manifest["context"] == ["tests/test_sign_in.py"]
    transcript = read(recorder.folder / "transcript.md")
    assert "- `app/main.py`: changed by the backend agent" in transcript
    assert f"python -m orchestrator --apply {recorder.folder}" in transcript
    # The log shows the orchestrator directing each agent.
    assert events[:4] == [
        line("project", f"{project_dir.resolve()} | 1 context file"),
        line("files", "backend: app/main.py"),
        line("files", "frontend: static/chat.html"),
        line("== round 1 of 3 =="),
    ]
    assert line("-> backend", "edit app/main.py | sends: task, 1 context file, 1 own file") in events
    assert line("<- backend", "changed app/main.py (+4 -0) | 1.5 s") in events
    assert line("-> frontend",
                "edit static/chat.html | sends: task, 1 context file, 1 own file, 1 back-end file (read-only)") in events
    assert line("<- frontend", "changed static/chat.html (+1 -1) | 1.5 s") in events
    assert line("-> reviewer", "review the changes | sends: task, 1 context file, 2 changed with diffs, 0 unchanged") in events
    assert events[-2:] == [
        line("next", f"read {recorder.folder / 'changes.diff'}"),
        line("next", f"python -m orchestrator --apply {recorder.folder}"),
    ]
    assert read(recorder.folder / "run.log") == "".join(e + "\n" for e in events)


def test_the_project_is_untouched_by_a_run(project_dir):
    before = {p: p.read_bytes() for p in project_dir.rglob("*") if p.is_file()}
    client = FakeModelClient(
        files_reply({"app/main.py": "app = 2\n"}), files_reply({"static/chat.html": "<p>2</p>\n"}), verdict(True),
    )
    orchestrator, _, _ = make_run(project_dir, client)

    orchestrator.run(TASK)

    after = {p: p.read_bytes() for p in project_dir.rglob("*") if p.is_file() and RUNS.name not in p.parts}
    assert after == before


def test_only_frontend_issues_skip_the_backend(project_dir):
    client = FakeModelClient(
        files_reply({"app/main.py": "app = 1\n"}), files_reply({"static/chat.html": "<p>1</p>\n"}),
        verdict(False, "One fix.", [("frontend", "Label the input")]),
        files_reply({"static/chat.html": "<p>2</p>\n"}), verdict(True, "Good."),
    )
    orchestrator, recorder, events = make_run(project_dir, client)

    result = orchestrator.run(TASK)

    assert client.roles == ["backend", "frontend", "reviewer", "frontend", "reviewer"]
    frontend_round_2 = client.prompts[3][1]
    assert "<p>1</p>" in frontend_round_2 and "- Label the input" in frontend_round_2
    assert line("route", "backend: 0 issues | frontend: 1 issue") in events
    assert line("skip", "backend: no issues, keeping its files") in events
    assert read(recorder.folder / "round-2" / "files" / "app" / "main.py") == "app = 1\n"
    assert result.final_files == {"app/main.py": "app = 1\n", "static/chat.html": "<p>2</p>\n"}


def test_a_back_end_change_makes_the_front_end_follow(project_dir):
    client = FakeModelClient(
        files_reply({"app/main.py": "app = 1\n"}), files_reply({"static/chat.html": "<p>1</p>\n"}),
        verdict(False, "One fix.", [("backend", "Rename the route")]),
        files_reply({"app/main.py": "app = 2\n"}), "No changes.", verdict(True, "Good."),
    )
    orchestrator, _, events = make_run(project_dir, client)

    orchestrator.run(TASK)

    assert client.roles == ["backend", "frontend", "reviewer", "backend", "frontend", "reviewer"]
    frontend_round_2 = client.prompts[4][1]
    assert "app = 2" in frontend_round_2 and "The back-end files changed this round" in frontend_round_2
    assert "Rename the route" not in frontend_round_2
    assert line("-> frontend", "follow the back-end changes in static/chat.html | sends: task, 1 context file, "
                "1 own file, 1 back-end file (read-only)") in events
    assert line("<- frontend", "no changes | 1.5 s") in events


def test_only_one_side_listed_never_calls_the_other(project_dir):
    client = FakeModelClient(
        files_reply({"static/chat.html": "<p>1</p>\n"}),
        verdict(False, "Fix.", [("backend", "The page calls a route that does not exist")]),
        files_reply({"static/chat.html": "<p>2</p>\n"}), verdict(True, "Good."),
    )
    orchestrator, _, events = make_run(project_dir, client, edits=("static/chat.html",))

    result = orchestrator.run(TASK)

    assert client.roles == ["frontend", "reviewer", "frontend", "reviewer"]
    assert line("files", "backend: none, so it is never called") in events
    # With no back-end files, every issue goes to the front end.
    assert "- The page calls a route that does not exist" in client.prompts[2][1]
    assert result.outcome == "approved"


def test_a_file_outside_the_agents_list_is_not_saved(project_dir):
    client = FakeModelClient(
        files_reply({"app/main.py": "app = 1\n", "tests/test_api.py": "hacked\n"}),
        files_reply({"static/chat.html": "<p>1</p>\n"}), verdict(True, "Good."),
    )
    orchestrator, recorder, events = make_run(project_dir, client)

    result = orchestrator.run(TASK)

    assert line("warning", "backend returned tests/test_api.py, which is not in its --edit list: not saved") in events
    assert "tests/test_api.py" not in result.final_files
    assert not any("test_api" in name for name in file_names(recorder.folder) if "/files/" in name)
    assert "Not saved: the backend agent returned `tests/test_api.py`" in read(recorder.folder / "transcript.md")


def test_a_cut_off_reply_stops_the_run_and_saves_nothing_from_it(project_dir):
    client = FakeModelClient(
        files_reply({"app/main.py": "app = 1\n"}),
        f"FILE: static/chat.html\n{FENCE}html\n<p>cut off",
    )
    orchestrator, recorder, events = make_run(project_dir, client)

    result = orchestrator.run(TASK)

    assert (result.outcome, result.failure) == ("failed", "frontend failed: TruncatedReply")
    assert line("<- frontend", "failed: TruncatedReply | 1.5 s") in events
    assert not (recorder.folder / "round-1" / "files").exists()
    assert not (recorder.folder / "final").exists() and not (recorder.folder / "changes.diff").exists()
    assert json.loads(read(recorder.folder / "manifest.json"))["outcome"] == "failed"


def test_not_approved_after_the_last_round_points_to_the_last_files(project_dir):
    client = FakeModelClient(
        files_reply({"app/main.py": "app = 1\n"}), files_reply({"static/chat.html": "<p>1</p>\n"}),
        verdict(False, "Still wrong.", [("frontend", "Contrast too low")]),
    )
    orchestrator, recorder, events = make_run(project_dir, client, max_rounds=1)

    result = orchestrator.run(TASK)

    assert result.outcome == "not approved"
    assert events[-1] == line(
        "next", f"only approved runs can be applied; the last files are in {recorder.folder / 'final' / 'files'}"
    )
    assert json.loads(read(recorder.folder / "manifest.json"))["outcome"] == "not approved"


# --- Command line: project mode --------------------------------------------------------------


def make_settings() -> OrchestratorSettings:
    return OrchestratorSettings(_env_file=None, openai_api_key="test-key", openai_base_url="",
                                openai_chat_model="test-model")


@pytest.fixture
def scripted_client(monkeypatch):
    """Make the command line use a FakeModelClient, and record the timeout it asked for."""
    timeouts = []

    def install(*replies) -> FakeModelClient:
        client = FakeModelClient(*replies)

        def build(settings, timeout):
            timeouts.append(timeout)
            return client

        monkeypatch.setattr(cli, "build_client", build)
        return client

    install.timeouts = timeouts
    return install


@pytest.mark.parametrize("argv, message", [
    (["--edit", "notes.txt"], "--edit notes.txt: has an unsupported file type"),
    (["--edit", "../x.py"], "--edit ../x.py: is outside the project folder"),
    (["--edit", "app/main.py", "--context", "tests/missing.py"], "--context tests/missing.py: does not exist"),
    (["--context", "tests/test_sign_in.py"], "--context needs at least one --edit"),
])
def test_invalid_project_input_exits_1_before_any_model_call(project_dir, capsys, scripted_client, argv, message):
    client = scripted_client()

    status = cli.main([TASK] + argv, settings=make_settings())

    assert status == 1
    assert message in capsys.readouterr().err
    assert client.prompts == []
    assert not (project_dir / RUNS).exists()


def test_project_mode_runs_with_a_longer_timeout(project_dir, capsys, scripted_client):
    client = scripted_client(
        files_reply({"app/main.py": "app = 1\n"}), files_reply({"static/chat.html": "<p>1</p>\n"}), verdict(True),
    )

    status = cli.main([TASK, "--edit", "app/main.py", "--edit", "static/chat.html",
                       "--context", "tests/test_sign_in.py"], settings=make_settings())

    assert status == 0
    assert scripted_client.timeouts == [300.0]
    assert client.roles == ["backend", "frontend", "reviewer"]
    assert "orchestrator  next         python -m orchestrator --apply" in capsys.readouterr().out
    assert read(project_dir / "app" / "main.py") == API_V0  # still untouched


def test_app_mode_keeps_the_usual_timeout(tmp_path, monkeypatch, scripted_client):
    monkeypatch.chdir(tmp_path)
    scripted_client(f"{FENCE}python\napp = 1\n{FENCE}", f"{FENCE}html\n<p>1</p>\n{FENCE}", verdict(True))

    assert cli.main(["a counter app"], settings=make_settings()) == 0
    assert scripted_client.timeouts == [120.0]


# --- Apply ----------------------------------------------------------------------------------


def approved_run(root, files=None, edits=("app/main.py", "static/chat.html")):
    """Run the project loop to an approved run whose builders return `files`; returns the run folder."""
    files = files or {"app/main.py": "app = 1\n", "static/chat.html": "<p>dark</p>\n"}
    backend = {p: t for p, t in files.items() if p.endswith(".py")}
    frontend = {p: t for p, t in files.items() if not p.endswith(".py")}
    replies = ([files_reply(backend)] if any(e.endswith(".py") for e in edits) else []) + [
        files_reply(frontend), verdict(True, "Good."),
    ]
    orchestrator, recorder, _ = make_run(root, FakeModelClient(*replies), edits=edits)
    assert orchestrator.run(TASK).outcome == "approved"
    return recorder.folder


class FakeTests:
    """Stands in for running pytest: returns the scripted status and records what the project held."""

    def __init__(self, status=0, root=None, error=None):
        self.status, self.root, self.error = status, root, error
        self.seen: dict[str, str] = {}

    def __call__(self) -> int:
        if self.root is not None:
            self.seen = {p: read(self.root / p) for p in ("app/main.py", "static/chat.html")}
        if self.error is not None:
            raise self.error
        return self.status


def collect():
    lines: list[tuple[str, str]] = []
    return lines, lambda label, text: lines.append((label, text))


def test_apply_writes_the_files_and_keeps_them_when_the_tests_pass(project_dir):
    run = approved_run(project_dir, edits=("app/main.py", "static/chat.html", "static/admin-login.html"),
                       files={"app/main.py": "app = 1\n", "static/chat.html": "<p>dark</p>\n",
                              "static/admin-login.html": "<form></form>\n"})
    tests = FakeTests(0, project_dir)
    lines, log = collect()

    assert apply_run(run, project_dir, tests, log) == 0

    assert tests.seen == {"app/main.py": "app = 1\n", "static/chat.html": "<p>dark</p>\n"}
    assert read(project_dir / "app" / "main.py") == "app = 1\n"
    assert read(project_dir / "static" / "admin-login.html") == "<form></form>\n"
    written = "changed app/main.py, changed static/chat.html, created static/admin-login.html"
    assert ("write", written) in lines
    assert ("decide", "tests passed -> keep the changes") in lines
    assert lines[-1] == ("result", f"applied: {written} | review with git diff, then commit")


def test_apply_restores_everything_when_the_tests_fail(project_dir):
    run = approved_run(project_dir, edits=("app/main.py", "static/admin-login.html"),
                       files={"app/main.py": "app = 1\n", "static/admin-login.html": "<form></form>\n"})
    lines, log = collect()

    assert apply_run(run, project_dir, FakeTests(1), log) == 1

    assert (project_dir / "app" / "main.py").read_bytes() == API_V0.encode()
    assert not (project_dir / "static" / "admin-login.html").exists()
    assert ("decide", "tests failed -> restore the project") in lines


def test_apply_restores_when_interrupted(project_dir):
    run = approved_run(project_dir)

    with pytest.raises(KeyboardInterrupt):
        apply_run(run, project_dir, FakeTests(error=KeyboardInterrupt()), collect()[1])

    assert (project_dir / "app" / "main.py").read_bytes() == API_V0.encode()
    assert (project_dir / "static" / "chat.html").read_bytes() == PAGE_V0.encode()


def test_apply_keeps_a_files_crlf_line_endings(project_dir):
    (project_dir / "static" / "chat.html").write_bytes(b"<p>light</p>\r\n")
    run = approved_run(project_dir, edits=("static/chat.html",), files={"static/chat.html": "<p>dark</p>\n<p>!</p>\n"})

    assert apply_run(run, project_dir, FakeTests(0), collect()[1]) == 0

    assert (project_dir / "static" / "chat.html").read_bytes() == b"<p>dark</p>\r\n<p>!</p>\r\n"


def test_apply_refuses_a_file_changed_since_the_run(project_dir):
    run = approved_run(project_dir)
    (project_dir / "static" / "chat.html").write_text("<p>edited by hand</p>\n", encoding="utf-8")
    tests = FakeTests(0)

    with pytest.raises(ProjectError, match="changed since the run: static/chat.html"):
        apply_run(run, project_dir, tests, collect()[1])

    assert read(project_dir / "app" / "main.py") == API_V0  # nothing written
    assert read(project_dir / "static" / "chat.html") == "<p>edited by hand</p>\n"


def test_apply_refuses_a_run_that_was_not_approved(project_dir):
    client = FakeModelClient(
        files_reply({"app/main.py": "app = 1\n"}), files_reply({"static/chat.html": "<p>1</p>\n"}),
        verdict(False, "No.", [("frontend", "Fix")]),
    )
    orchestrator, recorder, _ = make_run(project_dir, client, max_rounds=1)
    orchestrator.run(TASK)

    with pytest.raises(ProjectError, match="only approved runs can be applied; this run's outcome is 'not approved'"):
        apply_run(recorder.folder, project_dir, FakeTests(0), collect()[1])

    assert read(project_dir / "app" / "main.py") == API_V0


def test_apply_refuses_another_projects_run(project_dir, tmp_path):
    run = approved_run(project_dir)
    other = tmp_path / "other"
    other.mkdir()

    with pytest.raises(ProjectError, match="this run belongs to the project at"):
        apply_run(run, other, FakeTests(0), collect()[1])


def test_apply_refuses_a_folder_that_is_not_a_project_run(project_dir, tmp_path):
    with pytest.raises(ProjectError, match="is not a project-mode run folder"):
        apply_run(tmp_path, project_dir, FakeTests(0), collect()[1])


def test_apply_from_the_command_line(project_dir, monkeypatch, capsys):
    run = approved_run(project_dir)
    ran = []
    monkeypatch.setattr(cli, "run_project_tests", lambda root: ran.append(root) or 0)

    assert cli.main(["--apply", str(run)]) == 0

    assert ran == [project_dir]
    assert read(project_dir / "static" / "chat.html") == "<p>dark</p>\n"
    out = capsys.readouterr().out
    assert "orchestrator  decide       tests passed -> keep the changes" in out


@pytest.mark.parametrize("extra", [[TASK], ["--task-file", "task.md"], ["--edit", "app/main.py"]])
def test_apply_takes_only_the_run_folder(project_dir, monkeypatch, capsys, extra):
    run = approved_run(project_dir)
    monkeypatch.setattr(cli, "run_project_tests", lambda root: pytest.fail("tests must not run"))

    assert cli.main(["--apply", str(run)] + extra) == 1

    assert "--apply takes only the run folder" in capsys.readouterr().err
    assert read(project_dir / "app" / "main.py") == API_V0


def test_apply_refusal_exits_1(project_dir, capsys):
    run = approved_run(project_dir)
    (project_dir / "app" / "main.py").write_text("changed\n", encoding="utf-8")

    assert cli.main(["--apply", str(run)]) == 1

    assert "changed since the run: app/main.py" in capsys.readouterr().err
