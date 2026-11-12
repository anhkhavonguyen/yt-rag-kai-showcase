# Design

## Context

- **The orchestrator** (`orchestrator/`, from `add-agent-orchestrator`) is a plain Python loop with three agents: back end, front end and reviewer. Each agent is one call to a Gemini model through the OpenAI-compatible API.
  - It builds only a standalone pair of files, `api.py` and `index.html`, in `orchestrator_runs/<stamp>/`. The prompts force toy-app rules: data in memory, routes under `/api/`, and `GET /` serving `index.html`.
  - Progress lines come from free-form `on_event` strings, such as `"  backend   writing api.py..."`. Those lines show what each agent is doing, but not the orchestrator's decisions.
  - `tests/test_orchestrator.py` checks the exact lines.
- **The app**: `/chat` is the "Customer Support" page, and `/admin` is the editor (`static/admin.html`).
  - `/admin` answers 200 to anyone. Its script calls `GET /admin/verify` with a token kept in `sessionStorage` and shows an inline token form.
  - `/seed` accepts `Authorization: Bearer <SEED_TOKEN>` only (`require_seed_token` in `app/main.py`).
  - Both pages have their own copy of a light palette in `:root`.
- **Constraints**:
  - Free stack only (Render free tier and Gemini free tier), so no paid services, no new secrets, and no new Python packages. FastAPI form parsing would need `python-multipart`, which isn't installed.
  - The Render free instance sleeps and restarts, so server-side session state would be lost.
  - Uvicorn runs behind Render's proxy without trusted forwarded headers, so `request.url.scheme` is `http` even though browsers use `https`.
- **Specs**: `openspec/specs/` is empty. The capabilities this change modifies live in merged but unarchived changes (see proposal).

## Goals / Non-Goals

**Goals:**
- The orchestrator can change real project files, with the person reviewing before anything reaches the project, and tests as the gate.
- The log reads as the orchestrator directing its sub-agents: who got which job, with which inputs, what came back, and why it routed or stopped.
- The agents, not a person, write the app part of this change. Hand edits happen only after a failed attempt, and they are recorded.

**Non-Goals:**
- A model deciding the flow. The orchestrator stays plain Python.
- Agents writing tests, docs or config, or deleting files.
- A layout redesign. Only colors and focus styles change, and page structure and behavior stay as they are.
- Light mode, a theme toggle, or following the system preference.
- Per-user accounts, rate limiting of sign-in, CSRF tokens, or CORS changes (see Risks).
- Fixing the old `innerHTML` rendering of chat messages. If the agents fix it, that's fine as long as the behavior is the same.

## Decisions

### 1. Two phases: hand-written tool, agent-written feature
The orchestrator's project mode is written and tested by hand first, and committed. Then the agents use it to write the app files. We don't ask the agents to extend the orchestrator: a reviewer that only reads code is a weak gate for the tool that applies code to the repo.

### 2. Owner by file type
`.py` files belong to the back-end agent. `.html`, `.css` and `.js` files belong to the front-end agent. This mirrors the two roles without new flags. The alternative, `--backend PATH` and `--frontend PATH`, adds flags and still needs the same checks.

### 3. Whole files with path labels, cut-off replies rejected
A builder's reply lists files like this:

````
FILE: static/chat.html
```html
...whole file...
```
````

Reading the reply:
- The parser accepts `FILE:` with or without `#`, `**` or backticks around it.
- A file's text runs to the last closing fence before the next `FILE:` line, or before the end of the reply. A fence inside a file, such as a Markdown example in a string, doesn't cut the file short.
- A file block with no closing fence means the reply was cut off. That is a `ModelCallError("TruncatedReply")` for that agent, and nothing from the reply is saved.

We considered two other formats:
- **Unified diffs from the model.** Models often get hunk line numbers wrong.
- **JSON with file contents.** Escaping 20 KB of HTML in JSON is a common source of failures.

At these file sizes (each under 30 KB), whole files are the most reliable.

### 4. A separate project-mode loop
A new `ProjectOrchestrator` in `orchestrator/orchestrator.py` handles project mode:
- either builder can be optional (no files of its type);
- a reply with no files is valid;
- the state is a dict of path to text per owner;
- the reviewer gets diffs.

It reuses `issues_for`, the dispatch log helper and the recorder. App mode's `Orchestrator` stays almost as it is, because its README walks through that loop step by step. We rejected one generic loop, because it would hide app mode's simple flow behind abstractions that only project mode needs.

### 5. Project-mode prompts
Project mode has three new prompts, and the toy-app prompts stay the same:
- **Builders**: "You change an existing project. Keep every behavior the task doesn't ask to change. Return only the files you change, each complete, as `FILE:` blocks. Make the context tests pass. Don't add dependencies."
- **Reviewer**: checks the task and the context tests, flags deleted behavior that the task didn't ask for, and assigns `.py` issues to the back end and `.html`, `.css` and `.js` issues to the front end.

### 6. The dispatch log
`DispatchLog` (in `orchestrator/orchestrator.py`) builds every line, prints it through `on_event`, and appends it to `run.log`. It takes a `clock` (time of day) and a `timer` (for call durations), so the tests are deterministic. The lines use ASCII only (`->` and `<-`), because `→` turns into `?` on Windows code-page consoles. App mode looks like this:

```
19:42:01 orchestrator  round 1 of 3
19:42:01 orchestrator  -> backend   write api.py | sends: task
19:42:19 orchestrator  <- backend   api.py, 2.2 KB | 18.1 s
19:42:19 orchestrator  -> frontend  write index.html | sends: task, api.py
19:43:02 orchestrator  <- frontend  index.html, 12.0 KB | 43.0 s
19:43:02 orchestrator  -> reviewer  review | sends: task, api.py, index.html
19:43:20 orchestrator  <- reviewer  changes requested (1 issue: 1 frontend): Delete buttons lack labels. | 18.0 s
19:43:20 orchestrator  decide      not approved, round 1 of 3 -> round 2
19:43:20 orchestrator  round 2 of 3
19:43:20 orchestrator  route       backend: 0 issues -> skip, keep api.py | frontend: 1 issue
19:43:20 orchestrator  -> frontend  fix 1 issue in index.html | sends: task, api.py, index.html, 1 issue
...
19:44:05 orchestrator  decide      approved -> stop
19:44:05 orchestrator  result      approved after 2 rounds | folder: orchestrator_runs/20261112-194201
19:44:05 orchestrator  next        cd orchestrator_runs/20261112-194201/final && python -m uvicorn api:app
```

In project mode:
- `sends:` names the context files and the paths.
- `<-` lists the changed paths with their line counts (`+42 -7`).
- A warning line names any path an agent wasn't allowed to write.
- The last line shows the `--apply` command.

We considered two alternatives:
- **JSON lines.** Easy for machines, hard for the person watching.
- **Python `logging`.** Needs setup, and the format would differ from what's printed.

### 7. Saving every call
`RecordingClient` wraps the shared `ModelClient`, one instance per agent with the agent's name. It writes `round-N/calls/NN-<agent>.md` with three sections:
- **System prompt**, the agent's prompt;
- **Message**, what the orchestrator sent;
- **Reply**, the raw reply, or `failed: <ErrorType>`.

The orchestrator tells the recorder the current round. The API key never appears in a prompt, and error text keeps the error type only, as `llm.py` already does.

### 8. Project files, checks and apply: `orchestrator/project.py`
- **Path checks** (spec: "Project mode lists the files…") run before any model call.
- **Starting state**: the starting text and the SHA-256 of the bytes, or "missing" for a file that doesn't exist yet.
- **Diffs** use `difflib.unified_diff` with `a/` and `b/` prefixes.
- **`apply_run(run_folder, project_root, run_tests)`** works in this order:
  1. Read `manifest.json` and check the outcome, the project folder and the hashes.
  2. Keep the current bytes of each file, or `None` for a file that doesn't exist yet.
  3. Write the final files.
  4. Call `run_tests()`, which by default runs `subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=root)` with the output streamed to the console.
  5. If the tests don't pass, restore the kept bytes and delete created files. This step runs in a `finally` block, so Ctrl+C also restores.

  `run_tests` is passed in, so orchestrator tests never run pytest inside pytest.

Running the tests runs model-written code. That is acceptable only here: apply is a separate command, run after the person has read `changes.diff`, and `tests/conftest.py` blocks network services. The build run itself still never runs anything.

Project mode uses a 300-second model timeout instead of 120, because the front-end reply can be about 40 KB. `OpenAICompatibleClient` gets a `timeout` parameter.

### 9. A stateless session cookie signed with `SEED_TOKEN`
`app/core/admin_session.py` holds the session logic. Its interface is fixed in the task file, and the acceptance tests import it:

```python
COOKIE_NAME = "admin_session"
SESSION_SECONDS = 8 * 60 * 60
def issue(token: str, now: float) -> str: ...            # "v1.<issued_at>.<hex HMAC-SHA256(token, 'admin-session:v1:<issued_at>')>"
def is_valid(value: str | None, token: str, now: float) -> bool: ...  # signature with compare_digest, 0 <= now - issued_at < SESSION_SECONDS
```

We considered three other designs:
- **Server-side sessions in memory**: lost when the free instance sleeps.
- **A Supabase sessions table**: more infrastructure for one owner.
- **Starlette `SessionMiddleware`**: needs `itsdangerous` and a new secret.

Keying the signature with `SEED_TOKEN` gives "rotating the token ends every session" for free.

The trade-off: you can't revoke one session alone. Sign out clears the cookie in that browser only.

### 10. App routes
In `app/main.py`:
- **`admin_signed_in(request)`**: true when `SEED_TOKEN` is unset, or when the cookie `is_valid`.
- **`GET /admin`**: serves `static/admin.html`, or answers 303 to `/admin/login`. Both answers carry `Cache-Control: no-store`.
- **`GET /admin/login`**: serves `static/admin-login.html`, or answers 303 to `/admin`.
- **`POST /admin/login`**: reads `await request.json()` by hand, not through a pydantic body, because FastAPI would answer 422 and the spec wants 401 for a bad body. It compares the token with `hmac.compare_digest`. On success it sets the cookie (`httponly=True`, `samesite="strict"`, `path="/"`, and `secure` when `ENVIRONMENT=production`) and answers 204. On failure it logs "Admin sign-in failed" without the token and answers 401.
- **`POST /admin/logout`**: deletes the cookie with the same attributes and answers 204.
- **`require_seed_access`** replaces `require_seed_token` on `/seed`. It accepts the bearer token as before, or a valid cookie when the host in `Origin` equals the `Host` header. Hosts are compared, not schemes, because of the proxy (see Context).
- **`GET /admin/verify`** is removed.

### 11. Shared theme tokens with a contrast test
`static/theme.css` defines these `:root` tokens as `#rrggbb` values: `--bg`, `--surface`, `--surface-raised`, `--text`, `--text-muted`, `--accent`, `--on-accent`, `--border`, `--danger`, `--success` and `--focus`. It also sets `color-scheme: dark`, base styles for `body`, form controls, buttons and links, and a `:focus-visible` outline in `--focus`. Each page also has `<meta name="color-scheme" content="dark">`.

`tests/test_theme.py` reads the tokens and checks the WCAG contrast pairs from the `ui-theme` spec:
- at least 4.5:1 for `text`, `text-muted`, `danger` and `success` on the backgrounds, and for `on-accent` on `accent`;
- at least 3:1 for `accent` and `focus` against `bg`.

The test also checks that each page links the stylesheet, has no hex colors in its own styles, and loads nothing external.

The task file suggests a palette that passes all of these checks (checked during planning):

```
--bg #0f1117  --surface #181b23  --surface-raised #222632  --text #e7e9ee  --text-muted #a4abba
--accent #8b93ff  --on-accent #0f1117  --border #3a4050  --danger #ff8a8a  --success #5fd4a0  --focus #ffd166
```

The agents may change it, but the test is the gate. A shared file was chosen over per-page `:root` copies, which drift apart; the two current pages already differ.

### 12. Tests first, as context for the agents
`tests/test_admin_sign_in.py`, `tests/test_theme.py` and the updated `tests/test_api.py` are written before the run. They cover:
- removing the `/admin/verify` tests;
- `/admin` now answering 303;
- `/chat` linking the theme.

They are given to every agent with `--context`, together with `app/core/config.py`, so the agents get the cookie name, the routes and the session interface exactly. `--apply` then enforces them. The tests stay uncommitted until apply, because they fail against the old code. They are committed together with the applied files, so every commit passes.

The run command:

```
python -m orchestrator --task-file orchestrator/tasks/dark-theme-admin-sign-in.md \
  --edit app/main.py --edit app/core/admin_session.py \
  --edit static/theme.css --edit static/chat.html --edit static/admin-login.html --edit static/admin.html \
  --context app/core/config.py --context tests/test_api.py \
  --context tests/test_admin_sign_in.py --context tests/test_theme.py
```

### 13. Evidence kept with the change
The orchestrator writes to `orchestrator_runs/`, which is git-ignored. To keep a record of how the feature was built, the applied run's `run.log`, `transcript.md` and `changes.diff` are copied to `openspec/changes/dark-theme-admin-sign-in-via-agents/agent-run/`. That folder holds the record of the orchestrator directing its sub-agents.

## Risks / Trade-offs

- **[Free-tier 429 or 503 errors, or about 20 calls a day on some models]** → One run makes at most 9 calls. A failed run is run again, after a wait or with `OPENAI_CHAT_MODEL` overridden for that one run (README).
- **[A builder drops code it shouldn't when it returns a whole `app/main.py`]** → The reviewer sees diffs and is told to flag behavior that was removed. The existing `test_api.py` covers `/`, `/healthz`, `/documents`, `/answer` and `/seed`, and apply rolls back when it fails.
- **[The agents never get approval, or their output fails the tests after 3 attempts]** → Start from the best run's `final/files/` by hand. Fix the files, note every hand edit under the task in `tasks.md`, and keep the run log as evidence. The change doesn't pretend the agents did work they didn't.
- **[Apply runs model-written code]** → It happens only in the separate `--apply` step, after the diff has been read. Network services are blocked by `conftest.py`, and the files are restored when the tests fail.
- **[A stolen session cookie is valid for up to 8 hours]** → The cookie is HttpOnly, Secure in production and `SameSite=Strict`. Rotating `SEED_TOKEN` in Render ends every session.
- **[Guessing the token through `/admin/login`, with no rate limit]** → Render's `generateValue` token is long and random. Failed attempts are logged. A rate limit is left for later.
- **[CORS allows `*` with credentials]** → `SameSite=Strict` keeps the cookie off cross-site requests, and `/seed` also checks that `Origin` matches the host. Tightening CORS is a separate change.
- **[Progress lines change in app mode too]** → Only people read these lines. The README example and the tests are updated in the same commit.
- **[Old admin tabs]** → After the deploy, an open old admin page calls the removed `/admin/verify` and gets 404. Reloading lands on the sign-in page.

## Migration Plan

1. Branch from `origin/main`.
2. Phase 1: hand-written orchestrator changes, with tests and the README. Commit, CI green.
3. Phase 2: write the task file (commit) and the acceptance tests (no commit yet), run the orchestrator, read `changes.diff`, `--apply`, check in a browser, update the docs, then commit the tests, the applied files, the docs and the `agent-run/` evidence together.
4. Open a PR, wait for CI, then merge. Render deploys after the checks pass. On the deployed URL:
   - `/admin` redirects to the sign-in page;
   - the `SEED_TOKEN` signs in;
   - saving works;
   - Sign out works.
5. **Rollback**: revert the merge commit. The old code ignores the `admin_session` cookie, and the old admin page asks for the token again. No data or schema changes.
