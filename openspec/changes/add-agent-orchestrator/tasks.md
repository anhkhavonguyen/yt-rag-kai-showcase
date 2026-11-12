# Tasks

## 1. Setup

- [x] 1.1 Create a branch from `main` (not from `move-kb-editor-to-admin-page`) and verify `git log -1` shows the `main` head
- [x] 1.2 Create the `orchestrator/` package with empty `__init__.py`, `__main__.py`, `config.py`, `llm.py`, `agents.py`, `orchestrator.py` and `recorder.py`, and verify `python -c "import orchestrator"` succeeds with no `SUPABASE_*` variables set
- [x] 1.3 Add `orchestrator_runs/` to `.gitignore` and `.dockerignore`, and verify `git check-ignore orchestrator_runs/x` prints the path

## 2. Settings and model client

- [x] 2.1 Implement `OrchestratorSettings` in `config.py` (only `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_CHAT_MODEL`; `.env` read with `extra="ignore"`; timeout 120 s and 1 retry as constants), and verify with tests in `tests/test_orchestrator.py` that it loads with no Supabase variables and that an empty base URL resolves to `https://api.openai.com/v1`
- [x] 2.2 Implement the `ModelClient` protocol, `OpenAICompatibleClient` and `ModelCallError` in `llm.py`, and verify with tests that the client sends the configured base URL, key and model name, and that an SDK exception whose message contains a fake key becomes a `ModelCallError` holding only the error type and HTTP status
- [x] 2.3 Add a `FakeModelClient` test helper that returns scripted replies, records each `(system, user)` prompt, and can raise on a chosen call; verify it is used by every orchestrator test and that no test constructs `OpenAICompatibleClient` against the network

## 3. Builder and reviewer agents

- [x] 3.1 Implement page extraction in `agents.py` (first `html` fence, else first fence, else whole reply; empty raises `ModelCallError("EmptyPage")`), and verify with tests for each of the spec's "builder writes one self-contained page" scenarios
- [x] 3.2 Implement `BuilderAgent` with the system prompt from design.md, and verify with tests that round 1's prompt contains only the task, and a later round's prompt contains the task, the previous page and every issue
- [x] 3.3 Implement `Review` and `ReviewerAgent` with the JSON-only system prompt and lenient parsing (fence stripping, fallback to not approved with the raw reply as the single issue), and verify with tests for an approved verdict, a verdict with issues, a fenced verdict, and a free-text reply
- [x] 3.4 Make both agents tag a `ModelCallError` with their name (`builder` or `reviewer`), and verify with a test that a failing reviewer call reports `reviewer`

## 4. Run recorder

- [x] 4.1 Implement `recorder.py`: create `<out-dir>/<YYYYMMDD-HHMMSS>` with `exist_ok=False` and a `-2`, `-3` suffix on a name clash; write `round-N.html` and `review-N.json` as each is ready; write `final.html` and `transcript.md` at the end; verify with a `tmp_path` test that two recorders started in the same second get separate folders
- [x] 4.2 Verify with a test that `transcript.md` lists the task, each round's verdict and issues, and the outcome, and that nothing is written outside the run folder

## 5. Orchestrator loop

- [x] 5.1 Implement `Orchestrator.run(task)` in `orchestrator.py`: the build-review loop up to `max_rounds`, issues (or the summary when the issue list is empty) passed to the next builder call, recorder calls after each step, and a `RunResult` with outcome `approved`, `not approved` or `failed`; verify with a test that approval in round 2 of 3 stops after 4 model calls and the final page equals the round 2 page
- [x] 5.2 Verify with a test that a run never approved in 3 rounds makes exactly 6 model calls, has outcome `not approved`, and keeps the round 3 issues
- [x] 5.3 Emit progress through the `on_event` callback at each step in the spec, plus a warning for an unreadable verdict; verify with a test that collects events into a list and checks their order for a one-round approved run
- [x] 5.4 Handle `ModelCallError`: stop, record outcome `failed` with the agent name and error type, write the transcript; verify with a test that a reviewer failure in round 1 leaves `round-1.html` and `transcript.md`, and that a fake key from the error message appears in no event and no saved file

## 6. Command line and guide

- [x] 6.1 Implement `__main__.py` with `argparse` (`task`, `--max-rounds` default 3 within 1–10, `--out-dir` default `orchestrator_runs`), the up-front checks for empty task, out-of-range limit and missing `OPENAI_API_KEY`, `print` as the event callback, and exit status 0 / 2 / 1; verify with tests that call `main([...])` with a patched client factory and assert exit codes and that no model call is made for each invalid input
- [x] 6.2 Write `orchestrator/README.md` with the flow diagram and the "what each agent receives" table from design.md, the Gemini `.env` settings, the run command, a sample console output, what the run folder contains, and a note to read `final.html` before opening it; verify every command in it runs as written
- [x] 6.3 Add a short "Agent orchestrator" section to the root `README.md` linking to `orchestrator/README.md`, and verify the link resolves on GitHub's file view

## 7. Integration checks

- [x] 7.1 Run `ruff check .` and `pytest` and verify both pass with no network access
- [x] 7.2 With Gemini settings in `.env`, run `python -m orchestrator "a to-do list page with a dark mode toggle"` and verify the console shows each step, the run folder has the files the spec lists, `final.html` opens and works in a browser, and the exit status matches the printed outcome
- [x] 7.3 Run `python -m orchestrator "a counter page" --max-rounds 1` and verify it makes at most 2 model calls and exits 0 or 2 according to the verdict

Groups 1–7 built and verified the first version, with one front-end builder. Groups 8–11 replace that builder with the back-end and front-end agents described in the revised proposal, spec and design.

## 8. Back-end and front-end agents

- [x] 8.1 Generalize page extraction to `extract_code(reply, language)` (first fence tagged with that language, else first fence, else whole reply; empty raises `ModelCallError("EmptyCode")`), and verify with tests for `python` and `html` replies in a fence, without a fence, cut off, and empty
- [x] 8.2 Implement `BackendAgent` with the back-end prompt from design.md (one FastAPI file, `app`, in-memory data, routes under `/api/`, `GET /` returns `index.html` from its own folder), and verify with tests that round 1's prompt contains only the task, a later round's prompt contains the task, the previous `api.py` and every backend issue, and a failure is tagged `backend`
- [x] 8.3 Replace `BuilderAgent` with `FrontendAgent` (receives the current `api.py`; prompt says to call relative `/api/` URLs), and verify with tests that round 1's prompt contains the task and `api.py`, a later round's prompt contains the previous page and its issues, a rebuild with no issues asks it to update for the new `api.py`, and a failure is tagged `frontend`

## 9. Reviewer with owner-tagged issues

- [x] 9.1 Add `Issue(owner, text)` and change `Review.issues` to a list of issues; give the reviewer the task, `api.py` and `index.html` and the prompt from design.md; verify with tests that the prompt contains all three and that an approved verdict and a verdict with backend and frontend issues are read correctly
- [x] 9.2 Read verdicts leniently: plain-string issues and unknown owners become owner `both`, owners such as `Back-end` are normalized, a fenced or wrapped verdict is read, and an unreadable reply becomes one `both` issue; verify each case with a test

## 10. Routing loop and run folder

- [x] 10.1 Rewrite `Orchestrator.run` for the three agents with the routing rules in the spec, and verify with tests: only frontend issues → round 2 makes 2 calls and keeps round 1's `api.py`; a backend issue → round 2 makes 3 calls and the front-end agent gets the new `api.py`; an unowned issue → both agents get it; approval in round 2 → the final files equal round 2's
- [x] 10.2 Verify with a test that a run whose every review has a backend issue makes exactly 9 calls in 3 rounds, ends `not approved`, and keeps the round 3 issues with their owners
- [x] 10.3 Change `recorder.py` to write `round-N/api.py`, `round-N/index.html` (kept files copied) and `round-N/review.json` as each is ready, `final/` when the run ends with an app, and a transcript that says which files were rebuilt or kept each round; verify with tests for an approved two-round run, a reviewer failure in round 1 (no `final/`), and that nothing is written outside the run folder
- [x] 10.4 Emit the events in the spec, including skipped builders, issue counts per owner, failures naming `backend`, `frontend` or `reviewer`, and how to run the final app; verify with a test of the exact event list for a one-round approved run, and that the secret-leak test still passes

## 11. Command line, guide and checks

- [x] 11.1 Wire the three agents in `__main__.py` and update the help text; verify the command-line tests pass with three scripted replies per round and exit statuses 0, 2 and 1
- [x] 11.2 Update `orchestrator/README.md` (flow diagram, what each agent receives, sample output, run folder, how to run the generated app, read both files before running) and the root `README.md` section; verify every command in them runs as written
- [x] 11.3 Run `ruff check .` and `pytest` and verify both pass with no network access
- [x] 11.4 With Gemini settings, run `python -m orchestrator "a to-do list app"` and verify the console shows each agent, the run folder matches the spec, `python -m uvicorn api:app` in `final/` serves the page at `http://127.0.0.1:8000`, adding an item through the page works, and the exit status matches the outcome
