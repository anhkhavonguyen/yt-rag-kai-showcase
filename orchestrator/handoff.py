"""Hand-off: answer the agents' model calls through files instead of a model API.

    python -m orchestrator --handoff --task-file task.md --edit app/main.py ...

For each call, the orchestrator writes <run>/handoff/NN-<agent>.request.md (the agent's
system prompt and the message) and waits for <run>/handoff/NN-<agent>.reply.md. Anything
that can read the request and write the reply can act as the agent. In this repository,
Claude Code sub-agents did, when the Gemini free tier was out of quota.

The orchestrator is unchanged: it routes issues, logs every hand-off and decides exactly
as it does with a model API. Only the source of the replies differs.
"""

import time
from collections.abc import Callable
from pathlib import Path

from .llm import ModelCallError

# A person or another agent writes whole files, which can take a while.
REPLY_WAIT_SECONDS = 3600.0
POLL_SECONDS = 1.0


def request_text(agent: str, number: int, system: str, user: str) -> str:
    """The request file: who is asked, the agent's system prompt, and the message."""
    return (
        f"# Request {number:02d}: {agent}\n\n"
        f"Act as the agent described in the system prompt, answer the message, and write your reply "
        f"to `{number:02d}-{agent}.reply.md` next to this file: only the reply, exactly as the system "
        f"prompt asks for it.\n\n"
        f"## System prompt\n\n{system}\n\n"
        f"## Message\n\n{user}\n"
    )


class HandoffChannel:
    """Exchanges request and reply files in one folder, numbering the calls in order."""

    def __init__(
        self,
        folder: Path,
        wait_seconds: float = REPLY_WAIT_SECONDS,
        poll_seconds: float = POLL_SECONDS,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.wait_seconds = wait_seconds
        self.poll_seconds = poll_seconds
        self.sleep = sleep
        self.clock = clock
        self._calls = 0

    def for_agent(self, agent: str) -> "HandoffClient":
        """A model client for one agent, so its files are named after it."""
        return HandoffClient(self, agent)

    def exchange(self, agent: str, system: str, user: str) -> str:
        """Write the request, then wait until the reply file is written completely and return its text."""
        self._calls += 1
        stem = f"{self._calls:02d}-{agent}"
        request = self.folder / f"{stem}.request.md"
        reply = self.folder / f"{stem}.reply.md"
        request.write_text(request_text(agent, self._calls, system, user), encoding="utf-8", newline="\n")

        deadline = self.clock() + self.wait_seconds
        seen_size: int | None = None
        while True:
            if reply.is_file():
                size = reply.stat().st_size
                # Complete when its size holds between two checks: the writer has finished.
                if size == seen_size:
                    text = reply.read_text(encoding="utf-8")
                    if not text.strip():
                        raise ModelCallError("EmptyReply")
                    return text
                seen_size = size
            if self.clock() >= deadline:
                raise ModelCallError("HandoffTimeout")
            self.sleep(self.poll_seconds)


class HandoffClient:
    """The model client one agent uses in hand-off mode."""

    def __init__(self, channel: HandoffChannel, agent: str):
        self.channel = channel
        self.agent = agent

    def complete(self, system: str, user: str) -> str:
        return self.channel.exchange(self.agent, system, user)
