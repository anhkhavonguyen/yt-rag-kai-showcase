"""Agent orchestrator, hand-off mode: agent calls answered through request and reply files.

Offline: the "other side" that writes the replies is a scripted sleep function, so no
test waits on a real clock, a model API or another process.
"""

from pathlib import Path

import pytest

import orchestrator.__main__ as cli
from orchestrator.config import OrchestratorSettings
from orchestrator.handoff import HandoffChannel
from orchestrator.llm import ModelCallError
from orchestrator.recorder import RunRecorder

FENCE = "```"


def read(path) -> str:
    return path.read_text(encoding="utf-8")


def answering_sleep(channel_folder, writes):
    """A stand-in for time.sleep: on each call, writes the next scripted text to the newest request's reply file.

    `writes` holds strings, or None for "write nothing this time".
    """
    pending = list(writes)

    def sleep(seconds):
        if not pending:
            return
        text = pending.pop(0)
        if text is None:
            return
        request = sorted(channel_folder.glob("*.request.md"))[-1]
        request.with_name(request.name.replace(".request.md", ".reply.md")).write_text(text, encoding="utf-8")

    return sleep


def test_request_holds_the_prompt_and_message_and_the_reply_is_returned(tmp_path):
    folder = tmp_path / "handoff"
    channel = HandoffChannel(folder, sleep=answering_sleep(folder, ["FILE: app/main.py\n```\napp = 1\n```\n"]))

    reply = channel.for_agent("backend").complete("You are a back-end developer.", "Task:\nAdd sign-in.")

    assert reply == "FILE: app/main.py\n```\napp = 1\n```\n"
    request = read(folder / "01-backend.request.md")
    assert request.startswith("# Request 01: backend\n")
    assert "write your reply to `01-backend.reply.md`" in request
    assert "## System prompt\n\nYou are a back-end developer.\n" in request
    assert "## Message\n\nTask:\nAdd sign-in.\n" in request


def test_a_reply_still_being_written_is_waited_for(tmp_path):
    folder = tmp_path / "handoff"
    channel = HandoffChannel(folder, sleep=answering_sleep(folder, ["FILE: a.py\n", "FILE: a.py\n```\nx = 1\n```\n"]))

    assert channel.for_agent("backend").complete("s", "u") == "FILE: a.py\n```\nx = 1\n```\n"


def test_no_reply_within_the_limit_is_a_handoff_timeout(tmp_path):
    now = [0.0]

    def sleep(seconds):
        now[0] += seconds

    channel = HandoffChannel(tmp_path / "handoff", wait_seconds=5, poll_seconds=1, sleep=sleep, clock=lambda: now[0])

    with pytest.raises(ModelCallError) as excinfo:
        channel.for_agent("reviewer").complete("s", "u")

    assert excinfo.value.error_type == "HandoffTimeout"
    assert now[0] == 5


def test_an_empty_reply_is_a_model_failure(tmp_path):
    folder = tmp_path / "handoff"
    channel = HandoffChannel(folder, sleep=answering_sleep(folder, ["  \n"]))

    with pytest.raises(ModelCallError) as excinfo:
        channel.for_agent("frontend").complete("s", "u")

    assert excinfo.value.error_type == "EmptyReply"


def test_each_agent_gets_its_own_numbered_files(tmp_path):
    folder = tmp_path / "handoff"
    channel = HandoffChannel(folder, sleep=answering_sleep(folder, ["one", None, "two", None, "three"]))
    recorder = RunRecorder(tmp_path / "runs")
    backend, frontend, reviewer = cli.build_project_agents(channel, recorder)

    backend.client.complete("s", "u")
    frontend.client.complete("s", "u")
    reviewer.client.complete("s", "u")

    assert sorted(p.name for p in folder.iterdir()) == [
        "01-backend.reply.md", "01-backend.request.md",
        "02-frontend.reply.md", "02-frontend.request.md",
        "03-reviewer.reply.md", "03-reviewer.request.md",
    ]


# --- Command line ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def no_model_api(monkeypatch):
    """Hand-off mode must never build the model API client."""

    def forbidden(settings, **kwargs):
        raise AssertionError("hand-off mode tried to build the model API client")

    monkeypatch.setattr(cli, "build_client", forbidden)


def scripted_channel(replies):
    """A HandoffChannel whose replies are written by a scripted 'other side'."""

    class Scripted(HandoffChannel):
        def __init__(self, folder):
            super().__init__(folder)
            self.sleep = answering_sleep(self.folder, [r for reply in replies for r in (reply, None)])

    return Scripted


def test_handoff_runs_without_an_api_key_and_logs_where_answers_come_from(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(cli, "HandoffChannel", scripted_channel([
        f"{FENCE}python\napp = 1\n{FENCE}",
        f"{FENCE}html\n<p>counter</p>\n{FENCE}",
        '{"approved": true, "summary": "Good.", "issues": []}',
    ]))

    status = cli.main(["a counter app", "--handoff"], settings=OrchestratorSettings(_env_file=None))

    assert status == 0
    (run,) = (tmp_path / "orchestrator_runs").iterdir()
    log = read(run / "run.log").splitlines()
    handoff = Path("orchestrator_runs") / run.name / "handoff"  # relative, as given with --out-dir
    assert log[0].endswith(f"orchestrator  model        hand-off: requests and replies in {handoff}")
    assert any("orchestrator  <- reviewer  approved: Good." in line for line in log)
    assert sorted(p.name for p in (run / "handoff").iterdir()) == [
        "01-backend.reply.md", "01-backend.request.md",
        "02-frontend.reply.md", "02-frontend.request.md",
        "03-reviewer.reply.md", "03-reviewer.request.md",
    ]
    assert "hand-off: requests and replies in" in capsys.readouterr().out


def test_api_mode_logs_the_model_and_endpoint(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    class Scripted:
        replies = [f"{FENCE}python\napp = 1\n{FENCE}", f"{FENCE}html\n<p>1</p>\n{FENCE}",
                   '{"approved": true, "summary": "Good.", "issues": []}']

        def complete(self, system, user):
            return self.replies.pop(0)

    monkeypatch.setattr(cli, "build_client", lambda settings, **kwargs: Scripted())
    settings = OrchestratorSettings(_env_file=None, openai_api_key="k", openai_base_url="", openai_chat_model="m-1")

    assert cli.main(["a counter app"], settings=settings) == 0

    first = capsys.readouterr().out.splitlines()[0]
    assert first.endswith("orchestrator  model        m-1 at https://api.openai.com/v1")
