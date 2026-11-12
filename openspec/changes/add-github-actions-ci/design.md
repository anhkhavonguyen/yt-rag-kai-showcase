# Design

## Context

See `proposal.md` (Why) for motivation, and `specs/continuous-integration/spec.md` for the required behaviour. These facts about the current code shape the approach:

- **Settings are read at import time.** `app/core/config.py` creates `Settings()` at import time and requires `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY` and `OPENAI_API_KEY`. Every service module calls `get_settings()` when imported, so nothing in `app/` can be imported without those variables.
- **Service objects are created at import time.** `embedding_service`, `chat_service`, `chunker`, `rag_service` and `db` are module-level instances. `RAGService` stores references to the other services as instance attributes (`self.db`, `self.embedding_service`, `self.chat_service`). Creating the OpenAI and Anthropic clients makes no network call. Supabase clients are only created in `db.connect()`, which runs in the FastAPI lifespan.
- **Verified locally** (project venv, Python 3.12.10, all values placeholders):
  - With placeholder environment variables set, `import main` succeeds, and those values take precedence over a real local `.env`.
  - `TestClient(app)` used *without* a `with` block doesn't run the lifespan, so it never connects to Supabase.
  - `GET /` returns 200, and `POST /answer` with `top_k=0` returns 422.
- **Lint baseline.** `ruff check .` with the default rule set reports 11 findings in 7 files: F401 unused imports and F841 unused locals.
- **Root-level scripts look like tests.** `test_setup.py` sits in the repository root and defines `async def test_setup()`. pytest's default discovery would collect it, and it calls real services.
- **Python versions differ.** The Dockerfile uses `python:3.11-slim`, while the local venv runs Python 3.12. `requirements.txt` uses unpinned `>=` ranges.

## Goals / Non-Goals

**Goals:**
- Fast feedback, a few minutes per run, with each check shown as its own status.
- Tests that are deterministic and need no network or credentials, both in CI and on a developer machine that has a real `.env`.
- Leave runtime code alone apart from the lint fixes.

**Non-Goals:**
- Refactoring configuration loading or service construction. The keyless-mode change will revisit `config.py`.
- Code formatting enforcement (`ruff format`), broader lint rule sets, or type checking.
- Pinning or locking runtime dependencies.
- Pushing images, deploying, or replacing `DEPLOYMENT.md`.
- Coverage thresholds.

## Decisions

### 1. GitHub Actions as the CI platform
It is built into the repository host, needs no extra account, and is free for public repositories.
- Rejected: Google Cloud Build needs a billed GCP project.
- Rejected: third-party CI services (CircleCI and similar) need another account and integration.

### 2. One workflow, three parallel jobs: `lint`, `test`, `docker-build`
- The workflow lives in `.github/workflows/ci.yml`.
- Separate jobs give each check its own status, which satisfies "Run status reflects every check", and they run in parallel.
- `lint` installs only ruff and skips the runtime requirements, so it finishes in seconds.
- Rejected: a single job running every step in sequence. It is slower, and the first failure hides the results of later checks.

### 3. Workflow settings
- **Triggers:** `push` to `main`, `pull_request` targeting `main`, and `workflow_dispatch`.
- **Permissions:** workflow-level `permissions: contents: read`.
- **Concurrency:** grouped per workflow and ref, with `cancel-in-progress: true`, so a newer push cancels an outdated run.
- **Timeout:** `timeout-minutes: 10` per job.
- **Action versions:** official actions (`actions/checkout`, `actions/setup-python`) pinned to their current major version at implementation time.
- **pip cache:** setup-python's built-in pip cache, keyed on the requirements files.

### 4. Python 3.11 in CI
This matches the production image (`python:3.11-slim`), which is what actually ships.
- Rejected for now: a 3.11 + 3.12 matrix. It doubles test minutes for little gain at this size and can be added later (see Open Questions).

### 5. Development dependencies in `requirements-dev.txt`
- The file starts with `-r requirements.txt`, then adds `pytest`, `ruff` and `httpx`. `httpx` is listed explicitly because FastAPI's `TestClient` needs it, even though it is already a transitive dependency.
- `ruff` is pinned to an exact version so lint results don't change when ruff adds rules. `pytest` is pinned to a major version.
- The `lint` job doesn't install the runtime requirements. It installs only the `ruff==` line read from `requirements-dev.txt` (`pip install "$(grep '^ruff==' requirements-dev.txt)"`), so the version is defined in one place and CI matches local runs.
- The runtime `requirements.txt` and the Docker image are unchanged.
- Rejected: optional dependencies in `pyproject.toml`. The project has no packaging metadata and already uses requirements files.

### 6. Tool configuration in a new `pyproject.toml` (tool sections only)
- `[tool.ruff]`: `target-version = "py311"` and `extend-exclude` for `venv_yt_rag`. Ruff already respects `.gitignore`; the explicit entry is a safety net.
- `[tool.ruff.lint]`: `select = ["E4", "E7", "E9", "F"]`, written out explicitly. Newer ruff releases (for example 0.17) enable broader rule families by default, and 0.17.4 reports 118 findings on this codebase. Naming the rules keeps the lint scope at the classic minimal set, whatever the ruff version.
- `[tool.pytest.ini_options]`:
  - `testpaths = ["tests"]` stops pytest from collecting the root-level `test_setup.py`, which calls real services. Those three manual scripts stay as they are.
  - `pythonpath = ["."]` puts the repository root on the import path. A bare `pytest` command, unlike `python -m pytest`, doesn't add it, and the tests need it to import `app` and `main`.

### 7. Settings isolation in `tests/conftest.py`
- At the top of `conftest.py`, before anything in `app` is imported, set placeholder values for **every** settings variable: the three Supabase variables, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, and `AI_PROVIDER=openai`. Use direct assignment, not `setdefault`.
- Environment variables override `.env` values in pydantic-settings (verified), so a developer's real `.env` can't leak into tests.
- Rejected: making `config.py` lazy or skipping the `.env` file during tests. That changes runtime code and belongs to the keyless-mode change.

### 8. Test doubles at the service seams
- RAG tests replace the attributes on the `rag_service` instance (`embedding_service`, `db`, `chat_service`) with small fakes or `AsyncMock`s using `monkeypatch`.
- API tests patch the objects `app.main` imported (`app.main.rag_service`, `app.main.db`).
- This keeps doubles at the boundaries the code already has and adds no HTTP-mocking library.
- Rejected: mocking at the HTTP transport level (respx, VCR cassettes). That adds dependencies and couples tests to provider wire formats that the keyless-mode change is about to vary.

### 9. API tests use `TestClient(app)` without entering the lifespan
- `/healthz` is tested by patching `db.health_check` to return `True` and `False`.
- `/seed` and `/answer` are tested by patching the `rag_service` methods.
- Rejected: patching `db.connect` and running the lifespan. It is more brittle and adds nothing, since lifespan only calls Supabase.

### 10. Async service methods are tested with `asyncio.run(...)`
Plain synchronous test functions call `asyncio.run(...)`.
- Rejected: pytest-asyncio or the anyio plugin. They add a dependency and configuration for a handful of tests.

### 11. Container check is a plain `docker build`
- The `docker-build` job runs `docker build -t yt-rag:ci .` on `ubuntu-latest`, where Docker is preinstalled.
- No registry login, no push, no secrets.
- Rejected for now: `docker/build-push-action` with layer caching. It adds configuration and only saves time once builds become slow.

### 12. Lint fixes are minimal and keep behaviour
- Remove unused imports.
- For F841, drop the unused assignment but keep the call:
  - `database.health_check` still runs the query, because the query itself is the health probe.
  - The `progress.add_task(...)` calls in `chatbot.py` stay, because they draw the spinner.
- Remove the unused `rich.syntax.Syntax` import from `chatbot.py`'s optional-import block.

## Risks / Trade-offs

- **[Risk] Unpinned runtime dependencies (`>=`) can pull in a breaking release and turn CI red without any code change.** → This is partly intended: CI makes such breakage visible before deployment. The failure shows up as a dependency error in the `test` or `docker-build` job. A lockfile or constraints file is a possible follow-up.
- **[Risk] Test doubles can drift from real provider behaviour, so tests pass while real calls fail.** → The manual scripts (`test_setup.py`, `verify_rag.py`) remain for real-service checks. The keyless-mode change will add a real path through a free endpoint.
- **[Risk] Tests won't catch startup bugs, because the lifespan isn't run.** → This is accepted for now. Today the lifespan only connects to Supabase, which CI can't reach anyway.
- **[Trade-off] Local Python 3.12 and CI 3.11 can disagree on version-specific issues.** → CI matches production, which is what matters. A matrix can be added later.
- **[Trade-off] Private repositories spend free Actions minutes.** → Three short parallel jobs, cancellation of superseded runs, and pip caching keep usage low.

## Migration Plan

1. Merge the change to `main`. The workflow runs automatically on that push.
2. Confirm the first run on `main` is green, and the README badge shows "passing".
3. Optional, done by the repository owner in GitHub settings: add a branch protection rule on `main` that requires the `lint`, `test` and `docker-build` checks.

**Rollback:** delete or disable `.github/workflows/ci.yml`, or disable the workflow in the Actions tab. The other files (tests, dev requirements, config) don't affect the running application.

## Open Questions

- Should branch protection require these checks before merging? This is the owner's GitHub-settings decision and can be made after the first green run.
- Should a Python 3.12 matrix entry be added to match the local venv? It can be added any time without changing the specs.
