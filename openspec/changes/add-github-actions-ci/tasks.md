# Tasks

## 1. Tooling setup

- [x] 1.1 Create `requirements-dev.txt` containing `-r requirements.txt`, `ruff==<current release>` (exact pin), `pytest` pinned to its current major version, and `httpx`. Verify: `pip install -r requirements-dev.txt` succeeds in the project venv, and `ruff --version` prints the pinned version.
- [x] 1.2 Create `pyproject.toml` with tool sections only:
  - `[tool.ruff]`: `target-version = "py311"`, the default rule set, and `extend-exclude = ["venv_yt_rag"]`.
  - `[tool.pytest.ini_options]`: `testpaths = ["tests"]` and `pythonpath = ["."]`.

  Verify: `ruff check .` reports exactly the 11 baseline findings and nothing under `venv_yt_rag/`.

## 2. Lint baseline fixes (behaviour-preserving)

- [x] 2.1 Remove the unused imports:
  - `os` in `app/core/config.py`
  - `ErrorResponse` in `app/main.py`
  - `Dict` and `Any` in `app/models/responses.py`
  - `Tuple` in `app/services/rag.py`
  - `json` and `rich.syntax.Syntax` in `chatbot.py`
  - `json` in `verify_rag.py`

  Verify: `ruff check . --select F401` reports nothing.
- [x] 2.2 Drop the unused assignments but keep each call:
  - `result =` in `app/core/database.py` `health_check`. The query must still run, because it is the health probe.
  - `task =` at `chatbot.py` lines 328 and 415. The `progress.add_task(...)` calls stay.

  Verify: `ruff check .` exits 0.
- [x] 2.3 Check that the fixes changed no behaviour. Verify: `python -m py_compile chatbot.py verify_rag.py test_setup.py` succeeds, and with placeholder environment variables set, `python -c "import main"` imports cleanly.

## 3. Test harness

- [x] 3.1 Create `tests/conftest.py`:
  - At module top, before any `app` import, assign placeholder values to `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `OPENAI_API_KEY` and `ANTHROPIC_API_KEY`, and set `AI_PROVIDER=openai`.
  - Add shared fixtures: fake embedding, db and chat services; a `TestClient(app)` created without entering the lifespan.

  Add `tests/test_settings_isolation.py`, which asserts that `get_settings()` returns the placeholder keys. Verify: `pytest tests/test_settings_isolation.py` passes on this machine, where a real `.env` exists.

## 4. RAG pipeline tests

- [x] 4.1 Add `tests/test_chunker.py`:
  - Short text gives one chunk with id `<id>#1`.
  - Long text gives sequential ids `#1..#n`, and consecutive chunks share exactly the configured overlap words.
  - Empty or whitespace-only text gives no chunks.
  - `chunk_documents` combines chunks from several documents.

  Verify: `pytest tests/test_chunker.py` passes. Temporarily setting the overlap step to zero in the chunker makes a test fail; revert after checking.
- [x] 4.2 Add `tests/test_rag_service.py`, with fakes patched onto the `rag_service` instance:
  - `_prepare_context` keeps one chunk per base document id and caps the context at 4.
  - `_extract_citations` drops ids that weren't in the context, removes duplicates and keeps their order.
  - `answer_query` with no search results returns the "don't have enough information" text and `[]` citations.
  - `answer_query` with results returns citations and `debug.top_doc_ids` drawn from the context.
  - `seed_documents` hands chunks that carry embeddings to `db.upsert_chunks`.

  Verify: `pytest tests/test_rag_service.py` passes. Temporarily removing the valid-id filter in `_extract_citations` makes a test fail; revert after checking.

## 5. HTTP API tests

- [x] 5.1 Add `tests/test_api.py`, with `app.main.rag_service` and `app.main.db` patched:
  - `GET /` returns 200.
  - `/healthz` returns `ok` with `database_connected: true` when `db.health_check` returns `True`, and `degraded` with `false` when it returns `False`.
  - `POST /seed` with no body calls `seed_documents(None)` and returns `{"inserted": n}`.
  - `POST /seed` with `docs` passes them on as `chunk_id`/`source`/`text` dicts.
  - `POST /answer` returns `text`, `citations`, `debug.top_doc_ids` and `debug.latency_ms`.
  - `top_k` of 0 or 21, or a missing `query`, returns 422.

  Verify: `pytest` (the whole suite) passes, and none of the tests enters the lifespan or creates a Supabase client.

## 6. CI workflow and documentation

- [x] 6.1 Create `.github/workflows/ci.yml`:
  - Triggers: `push` to `main`, `pull_request` to `main`, and `workflow_dispatch`.
  - Workflow-level `permissions: contents: read`.
  - `concurrency` grouped per workflow and ref, with `cancel-in-progress: true`.
  - Three parallel jobs on `ubuntu-latest`, each with `timeout-minutes: 10`:
    - `lint`: Python 3.11; install the `ruff==` line from `requirements-dev.txt`; run `ruff check .`.
    - `test`: Python 3.11 with the pip cache; `pip install -r requirements-dev.txt`; run `pytest`.
    - `docker-build`: `docker build -t yt-rag:ci .`, with no login and no push.
  - Official actions pinned to their current major version.

  Verify: the file parses as YAML, and it contains no `secrets.` reference, no registry login and no push step.
- [x] 6.2 Update `README.md`:
  - Add a CI status badge for `.github/workflows/ci.yml` in the repository returned by `git remote get-url origin`.
  - Add a "Running checks locally" section listing `pip install -r requirements-dev.txt`, `ruff check .`, `pytest`, and optionally `docker build -t yt-rag:ci .`.

  Verify: running the documented commands from the repository root in the project venv gives the same pass result as tasks 2.2 and 5.1.

## 7. End-to-end verification on GitHub

- [ ] 7.1 Push the work to a branch and open a pull request targeting `main`, with no repository secrets configured. Verify: `lint`, `test` and `docker-build` all run and pass on the pull request.
- [ ] 7.2 On that pull request, push a temporary commit that adds an unused import under `app/`, then revert it. Verify: the `lint` job fails and reports the file and line, the run is marked failed on the pull request, and the revert turns it green again.
- [ ] 7.3 Merge to `main`. Verify: the run on `main` passes, its job summary shows the token had only `Contents: read`, no image was pushed, and the README badge shows "passing".

## Workflow follow-up

- Optional, done by the repository owner in GitHub settings: add a branch protection rule on `main` requiring the `lint`, `test` and `docker-build` checks.
- Archive the change once it is merged and the first run on `main` is green.
