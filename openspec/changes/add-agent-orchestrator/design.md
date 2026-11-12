# Design

## Context

See proposal.md for why. The constraints that shape the design:

- **Free model only.** The project already talks to Gemini through its OpenAI-compatible endpoint, using the `openai` SDK and the `OPENAI_BASE_URL`, `OPENAI_API_KEY` and `OPENAI_CHAT_MODEL` settings. The free tier has per-minute and per-day request limits (about 20 a day for some models), so a run must make few calls.
- **`app/` cannot be reused directly.** `app/core/config.py` requires the Supabase settings, and `app/services/chat.py` builds a RAG-specific `chat_service` with a customer-support prompt when it is imported. The orchestrator needs neither.
- **CI runs offline.** `pytest` runs with placeholder settings and no network (`tests/conftest.py`), and `ruff check .` lints the whole repository. New code must be testable without a real model.
- **Learning first.** The owner wants to understand the flow, so the code must make clear who calls whom, what each agent sees, and why an agent runs or is skipped.
- **A first version exists.** The single-builder version (one front-end builder plus the reviewer) is implemented and tested on this branch. The model client, settings, command line and recorder carry over; the agents, the loop and the run folder layout change.

## Goals / Non-Goals

**Goals:**
- One file per concept (model client, agents, orchestrator loop, run recorder, command line), small enough to read in one sitting.
- Every input and output of every agent is visible in the console or the run folder.
- The routing rules, the loop and its stopping rules are fully tested with a fake model.
- The final app runs with one command from its folder.

**Non-Goals:**
- Agent frameworks (LangGraph, CrewAI, AutoGen and similar). They hide the loop this change exists to show.
- Streaming model output, conversation memory, or parallel calls.
- Running, importing or testing the generated code. The reviewer only reads it; the user runs the app.
- A database in the generated app.

## Decisions

### The flow

```
                     task (from the command line)
                          │
                          ▼
                 ┌──────────────────┐
                 │   Orchestrator   │  holds: task, api.py, index.html, latest review, round
                 └──────────────────┘
       ① task (+ last api.py │    ▲ ② api.py
          + backend issues)  ▼    │
                 ┌──────────────────┐
                 │  Back-end agent  │  "write / fix api.py"            (round 1, or backend issues)
                 └──────────────────┘
       ③ task + api.py       │    ▲ ④ index.html
         (+ last page        ▼    │
          + frontend issues) ┌──────────────────┐
                 │ Front-end agent  │  "write / fix index.html"        (round 1, frontend issues,
                 └──────────────────┘                                   or api.py changed)
       ⑤ task + api.py       │    ▲ ⑥ verdict {approved, summary,
         + index.html        ▼    │            issues: [{owner, issue}]}
                 ┌──────────────────┐
                 │  Reviewer agent  │  "review both files against the task"
                 └──────────────────┘

        Orchestrator saves round-N/, then decides:
          approved                  → stop, outcome "approved"      (exit 0)
          not approved, rounds left → next round: route issues by owner, back to ①
          not approved, last round  → stop, outcome "not approved"  (exit 2)
          any model error           → stop, outcome "failed"        (exit 1)
```

What each agent receives:

| Round | Back-end agent | Front-end agent | Reviewer |
|---|---|---|---|
| 1 | task | task, api.py | task, api.py, index.html |
| n > 1 | only if it has issues: task, its last api.py, its issues | only if it has issues or api.py changed: task, current api.py, its last page, its issues | task, current api.py, current index.html |

### The orchestrator is code, not a model

The loop is a plain `for round in 1..max_rounds` in `orchestrator/orchestrator.py`. It runs the builders that need to run, then the reviewer, and reads `review.approved` to decide what happens next.

- **Why:** the flow is the same on every run and can be read top to bottom, which is the point of this change. It also costs no extra model calls.
- **Alternative considered:** a model-driven orchestrator that gets "build back end", "build front end" and "review" as tools and decides which to call. That is how many production agent systems work, but its path changes from run to run and is harder to debug. It is a natural next step: the agents' interfaces stay the same and only the loop is replaced.

### Issues are routed to the agent that owns them

Each issue in a verdict carries an owner, `backend` or `frontend`. In round 2 and later:

1. The back-end agent runs only if some issue is owned by `backend` or has no recognized owner. It gets those issues.
2. The front-end agent runs if some issue is owned by `frontend` or has no owner, **or** the back-end agent rebuilt `api.py` in this round. It gets its own issues; when it runs only because `api.py` changed, it is told to update the page for the new `api.py`.
3. A verdict that is not approved but lists no issues is treated as one unowned issue: its summary.

- **Why:** an agent that has nothing to fix keeps its file, which saves calls on the free tier and shows the routing decision in the output. The front-end page depends on the API, so a changed `api.py` always triggers a front-end rebuild; the reverse is not true. Sending unowned issues to both agents means no issue is dropped.
- **Alternative considered:** rebuilding both files every round. Simpler, but up to 50% more calls, and it hides the routing this change exists to teach.
- **Alternative considered:** a model deciding who fixes what. Non-deterministic, and an extra call per round.

### The API also serves the page

The back-end prompt requires `GET /` to return `index.html` from the same folder as `api.py` (a `FileResponse` with a path built from `__file__`), and every API route to sit under `/api/`. The front-end prompt says the page is served at `/` and must call the API with relative URLs such as `/api/items`.

- **Why:** page and API share one origin, so no CORS setup is needed, and the whole app runs with `python -m uvicorn api:app` from its folder. `fastapi` and `uvicorn` are already in `requirements.txt`.
- **Alternative considered:** opening `index.html` as a file and calling the API on another port. That needs CORS in every generated `api.py` and two steps to run.

### The front-end agent reads the real api.py

The front-end agent receives the full current `api.py` rather than a separate API description.

- **Why:** one source of truth, no second output format to ask for and parse, and the page cannot be built against a description that drifted from the code. The file is small (a few KB).
- **Alternative considered:** the back-end agent also writes an API description block, or the orchestrator extracts the routes from the code. Both add a second artifact that can disagree with `api.py`.

### Agents are stateless; the orchestrator holds the state

Each agent is a small class with a fixed system prompt and one method:

- `BackendAgent.build(task, previous_api=None, issues=None) -> str`
- `FrontendAgent.build(task, api, previous_page=None, issues=None) -> str`
- `ReviewerAgent.review(task, api, page) -> Review`

Each call sends one self-contained prompt. Nothing is remembered between calls.

- **Why:** the table above is the whole truth about what an agent knows. Prompt size stays bounded, and a round can be re-run from the saved files.
- **Alternative considered:** giving each agent its own growing chat history. It shows less clearly what the agent is reacting to, and the prompt grows each round.

### One small model client interface

`orchestrator/llm.py` defines a `ModelClient` protocol with one method, `complete(system: str, user: str) -> str`, and one implementation, `OpenAICompatibleClient`, which wraps `openai.OpenAI(base_url=..., api_key=..., timeout=..., max_retries=...)` and calls `chat.completions.create`.

- **Why:** agents depend on the protocol, so tests pass a `FakeModelClient` that returns scripted replies and records the prompts. The same client serves all three agents; they differ only in prompt.
- **Errors:** any SDK exception, or a reply with no text, is turned into `ModelCallError(error_type)` that carries only the exception class name and HTTP status, never the provider message. This follows the same rule as `ChatService` in `app/services/chat.py`. The agent adds its own name (`backend`, `frontend` or `reviewer`) so the console can say which one failed.

### Own settings, same variable names

`orchestrator/config.py` has `OrchestratorSettings(BaseSettings)` with only `openai_api_key` (default empty), `openai_base_url` (default empty, meaning `https://api.openai.com/v1`), and `openai_chat_model` (default `gpt-4o`, same as the app). It reads `.env` with `extra="ignore"`, so the Supabase and other app variables in `.env` are allowed but not needed. Timeout (120 seconds, because a whole file is generated per call) and retries (1) are constants in the same file.

### Extracting code from a reply

`extract_code(reply, language)` takes the content of the first code fence tagged with that language (`python` or `py` for the back end, `html` for the front end); if there is none, the first fence of any kind; if there is no fence, the whole reply. An unclosed fence (a cut-off reply) keeps everything after it. Whitespace is stripped. An empty result raises `ModelCallError("EmptyCode")`.

### Reviewer verdict as JSON, read leniently

The reviewer's system prompt asks for JSON only:

```json
{"approved": false, "summary": "one sentence",
 "issues": [{"owner": "backend", "issue": "what to fix"}]}
```

Parsing produces `Review(approved, summary, issues: list[Issue])`, with `Issue(owner, text)` and `owner` one of `backend`, `frontend` or `both`:

1. Try the content of a surrounding code fence, the whole reply, then the text from the first `{` to the last `}`.
2. For each issue: an object with `owner` and `issue` becomes an `Issue`; an owner is normalized (case, hyphens and spaces ignored, so `Back-end` is `backend`); any other owner, or a plain-string issue, becomes `both`.
3. If nothing can be read as a verdict: `Review(approved=False, summary="The reviewer's reply was not a valid verdict.", issues=[Issue("both", raw reply)])`, and the orchestrator prints a warning.

- **Why:** plain prompt-requested JSON works with any OpenAI-compatible provider. Accepting plain strings and odd owners keeps a slightly-off reply useful instead of failing the round.
- **Alternative considered:** `response_format` JSON schema or function calling. More reliable, but support differs between providers. It can be added inside `ReviewerAgent` later without changing anything else.

### Prompts keep the loop converging

- **Back end:** you are a back-end developer; reply with one complete Python file in one `python` fence; FastAPI, the application object named `app`; import only `fastapi`, `pydantic` and the standard library; data in memory, no database or files; every route under `/api/` with pydantic request models; validate input and return clear HTTP errors; `GET /` returns `index.html` from this file's folder; when given issues, fix every one and return the full file.
- **Front end:** you are a front-end developer; you are given `api.py`; reply with one complete HTML document in one `html` fence; all CSS and JavaScript inline; nothing external; the page is served at `/`, so call the API with relative `/api/` URLs, using only the routes, methods and JSON shapes `api.py` defines; show a readable message when a request fails; when given issues, fix every one and return the full page.
- **Reviewer:** you review a small app made of `api.py` and `index.html` against the task; a checklist for each file (the back end provides what the task needs under `/api/`, keeps data in memory, validates input, serves the page; the front end uses only routes `api.py` defines, has no obvious JavaScript errors, labels its controls, works on a phone, loads nothing external); list only issues that must be fixed, not style preferences; tag each with its owner; approve when none remain; reply with JSON only.

Telling the reviewer to skip style preferences is what stops the loop from running to the limit on small nitpicks.

### Run recorder writes as it goes

`orchestrator/recorder.py` creates the run folder at the start (`<out-dir>/<YYYYMMDD-HHMMSS>`, adding `-2`, `-3`, ... if the name exists, created with `exist_ok=False` so two runs cannot share one). Within a round, it writes each file the moment it is ready: `round-N/api.py` and `round-N/index.html` (a kept file is copied from the previous round, so every round folder is a complete, runnable app), then `round-N/review.json`. At the end it writes `final/api.py` and `final/index.html` when the run ends with an app, and always `transcript.md`, which records for each round whether each file was rebuilt or kept.

- **Why:** a run that fails in round 3 still leaves rounds 1 and 2 to study, and any round can be run on its own.

### Console output through a callback

The orchestrator takes an `on_event(message: str)` callback and calls it at each step listed in the spec, including skipped builders and, at the end, how to run the final app (`cd <run>/final`, then `python -m uvicorn api:app`, then open `http://127.0.0.1:8000`). The command line passes a print function; tests pass `list.append` and assert the order.

### Package layout

```
orchestrator/
  __init__.py
  __main__.py       # argparse, settings check, wiring of the three agents, exit codes
  config.py         # OrchestratorSettings, timeout and retry constants
  llm.py            # ModelClient protocol, OpenAICompatibleClient, ModelCallError
  agents.py         # BackendAgent, FrontendAgent, ReviewerAgent, Review, Issue, prompts, extract_code
  orchestrator.py   # Orchestrator.run(task) -> RunResult, routing rules
  recorder.py       # run folder, round folders, final/, transcript
  README.md         # the flow diagram, setup, an example run, how to run the app
```

It sits at the repository root, not under `app/`, because it is a separate tool and must not trigger `app`'s import-time setup. The Docker image will contain it (the Dockerfile copies the whole repository) but never runs it.

## Risks / Trade-offs

- [More calls per run, up to 9] → Builders with no issues are skipped; `--max-rounds` bounds the total; a 429 stops the run with outcome "failed", keeps finished rounds and names the error type.
- [Page and API disagree, for example the page calls a route that does not exist] → The front-end agent always sees the current `api.py` and is rebuilt whenever it changes; the reviewer checks both files together.
- [Reviewer never approves] → Bounded by `--max-rounds`; the reviewer prompt excludes style preferences; the final app and its open issues are still saved.
- [Reviewer approves an app that does not work] → Expected for a code-only review; the README says to run the app and check it. A tester agent that starts the app and calls it is a possible later addition.
- [Generated `api.py` does something harmful when run] → The tool never runs or imports it (spec: "Generated code is saved, never run"). The README says to read both files before running them; uvicorn binds to `127.0.0.1` by default.
- [Reply cut off on a long file] → The reviewer sees the broken file and asks for a fix in the next round; no `max_tokens` is set, so the provider default applies.
- [Prompts leak secrets] → Prompts contain only the task, the files and the review. The API key is passed to the SDK and never printed or saved; errors carry the type only.

## Migration Plan

Additive only: a new package, a new test file, two ignore-file lines and a README section. No deployment, data or configuration changes. Rollback is deleting `orchestrator/` and `tests/test_orchestrator.py`.

The single-builder version on this branch is replaced in place: `BuilderAgent` becomes `FrontendAgent`, `BackendAgent` is added, and the flat `round-N.html` / `review-N.json` files become `round-N/` folders. Nothing outside this branch used the first version.
