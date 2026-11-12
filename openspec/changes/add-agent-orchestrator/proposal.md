# Proposal

## Why

The owner wants to learn how multi-agent systems work by building a small but realistic one: an orchestrator that runs a back-end developer agent and a front-end developer agent, sends their work to a reviewer agent, and routes each review issue back to the agent that owns it, looping until the reviewer approves. Today the repository only has a single-call RAG chat, so there is no example of agents passing work to each other. A small tool that prints every step makes that flow easy to follow.

## What Changes

- **New command-line tool `python -m orchestrator "<task>"`.** The user describes a small web app in plain words, for example "a to-do list app". The tool runs four roles and prints each step as it happens.
- **Back-end agent.** Writes the app's API as one FastAPI file, `api.py`, with data kept in memory. The same file serves the page at `/`, so the finished app runs with one command.
- **Front-end agent.** Reads the current `api.py` and writes one self-contained page, `index.html` (HTML, CSS and JavaScript together), that calls the API.
- **Reviewer agent.** Reads the task and both files, and returns a verdict: approved or not, a one-line summary, and a list of issues, each tagged `backend` or `frontend`.
- **Orchestrator.** Plain Python code, not a model. Round 1 runs the back-end agent, the front-end agent, then the reviewer. In later rounds it sends each issue to the agent that owns it and runs only the agents with something to fix; the front-end agent also runs whenever `api.py` changed. It repeats up to a round limit (default 3). It is the only part that holds state. The agents remember nothing between calls.
- **Saved run folder.** Each run writes every round's files and review, the final app and a readable transcript to `orchestrator_runs/<timestamp>/`, so the flow can be studied and the app run afterwards. The folder is git-ignored.
- **Free model only.** The agents use the OpenAI-compatible settings the project already has (`OPENAI_BASE_URL`, `OPENAI_API_KEY`, `OPENAI_CHAT_MODEL`), so they run on the free Gemini tier. No new paid service, account or dependency.
- **Short guide.** `orchestrator/README.md` explains the flow with a diagram, an example run, and how to run the generated app.

Out of scope: a web page or API endpoint for the orchestrator, more agents than these three, agents running in parallel, the orchestrator choosing agents with a model, databases in the generated app, running or testing the generated code (the user runs the app), and editing this repository's own files. The design notes how some of these could be added later.

Assumptions (change them before implementing if they are wrong):
- The tool is a command-line program, not a page in the web app.
- The agents create a new standalone app; they do not change `app/` or `static/`.
- The orchestrator is fixed code, so the routing rules are the same on every run.

The first version of this change, with one front-end builder, is already implemented on this branch. This revision replaces that builder with the back-end and front-end agents.

## Capabilities

### New Capabilities
- `agent-orchestrator`: the multi-agent tool that turns a task description into a reviewed small web app, made of a FastAPI back end and a page that calls it. Covers how the task is accepted, what each agent receives and returns, how review issues are routed, the loop and its stopping rules, what a run saves, and how failures are reported.

### Modified Capabilities
None. The RAG API, chat page and admin page do not change.

## Impact

- **Code**: new top-level package `orchestrator/` with the agents, the orchestrator loop, a small model client and the command-line entry point. It does not import from `app/`, so it needs no Supabase settings.
- **Tests**: new `tests/test_orchestrator.py` using a fake model client. It runs offline in the existing CI, like the current tests.
- **Configuration**: reuses `OPENAI_API_KEY`, `OPENAI_BASE_URL` and `OPENAI_CHAT_MODEL` from `.env`. No new environment variables.
- **Dependencies**: none new. The tool uses `openai` and `pydantic-settings`; the generated app needs `fastapi` and `uvicorn`. All four are already in `requirements.txt`.
- **Repository files**: `.gitignore` and `.dockerignore` gain `orchestrator_runs/`. The README links to the orchestrator guide.
- **Deployment**: none. The tool runs on a developer machine; the Render service does not run it and its start command is unchanged.
- **Cost**: a run makes at most 3 model calls per round, so 9 with the default limit. A later round that only needs front-end fixes makes 2. This fits the free Gemini tier, but some models allow only about 20 calls a day, so `--max-rounds` matters.
