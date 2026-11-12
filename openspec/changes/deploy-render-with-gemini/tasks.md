# Tasks

Implement on a branch from `main` after `add-github-actions-ci` is merged. Group 1 needs the owner's free accounts. Every other code task is verified offline with `pytest` and `ruff check .`.

## 1. Free accounts and Gemini compatibility check (owner + implementer)

- [x] 1.1 Owner creates a Google AI Studio API key and a free Supabase project. Region: Southeast Asia, to match `render.yaml`. Run `sql/init_supabase.sql` in its SQL editor, then put the keys in the local `.env`, which is never committed. Verify: the SQL script's final query prints the success row, and `.env` has `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY` and the Gemini key in `OPENAI_API_KEY`.
- [x] 1.2 With a throwaway script kept outside the repository (scratchpad), send real requests to `https://generativelanguage.googleapis.com/v1beta/openai/`:
  - one chat completion on `gemini-3.8-flash`, with a system message, `temperature=0.1` and `max_tokens=1000`;
  - one `embeddings.create` on `gemini-embedding-2`, with a **list** of 3 texts and `dimensions=1536`.

  Verify: record in design.md Decisions 3–4 whether `dimensions` is honoured, ignored or rejected, and whether list input works. Set the `EMBEDDING_SEND_DIMENSIONS` and `EMBEDDING_BATCH_SIZE` values that `render.yaml` and `.env.example` will document.

  Result: `dimensions` is honoured and list input works (`true`, `100`). `gemini-3.8-flash` returned 503, so the chat model is `gemini-3.5-flash` (design Decision 2).

## 2. Configurable provider and embedding size (spec: model-provider)

- [x] 2.1 Add the settings `openai_base_url` (optional), `embedding_batch_size` (default 100) and `embedding_send_dimensions` (default true), and use the existing `embedding_dimensions`. In `tests/conftest.py`, set placeholders for every new setting (`OPENAI_BASE_URL` empty, `EMBEDDING_BATCH_SIZE`, `EMBEDDING_SEND_DIMENSIONS`, `EMBEDDING_DIMENSIONS=1536`). Extend `tests/test_settings_isolation.py` to cover them. Verify: `pytest tests/test_settings_isolation.py` passes, with a `.env` present that sets different values.
- [x] 2.2 Pass `base_url=settings.openai_base_url or DEFAULT_OPENAI_BASE_URL` (`https://api.openai.com/v1`) to `openai.OpenAI(...)` in `EmbeddingService` and `ChatService`. Don't pass `None`: the SDK then falls back to the raw `OPENAI_BASE_URL` environment variable, and an empty value gives an unusable client. Add tests asserting each client's `base_url`: the configured URL when it is set, and `https://api.openai.com/v1/` when it isn't. Verify: `pytest` passes.
- [x] 2.3 In `EmbeddingService.embed_texts`:
  - send at most `embedding_batch_size` texts per request, keeping the input order;
  - pass `dimensions` when `embedding_send_dimensions` is true;
  - enforce the size: use an exact-length vector as is, truncate a longer one and L2-normalize it, raise `ValueError` naming both sizes for a shorter one.

  Add `tests/test_embedding_service.py`, using a fake client, covering:
  - 250 texts make calls of 100, 100 and 50, and the results keep the input order;
  - a 3072-value vector becomes 1536 values with norm 1.0, and its direction equals the normalized prefix;
  - a short vector raises, and `rag.seed_documents` then writes nothing;
  - `dimensions` is sent or omitted per the setting.

  Verify: `pytest` and `ruff check .` pass.
- [ ] 2.4 Document the provider settings:
  - In `.env.example`, add a commented "Free: Google Gemini (OpenAI-compatible)" block with the base URL, model names, `EMBEDDING_DIMENSIONS` and the values from task 1.2. Note that `OPENAI_API_KEY` holds the Gemini key, and that switching the embedding model needs a re-seed.
  - In the README "AI Providers" section, describe `OPENAI_BASE_URL`.

  Verify: running the app locally with the Gemini block copied into `.env` gives a 200 from `POST /seed` and a 200 from `POST /answer` with citations.

## 3. Fallback answer (spec: question-answering)

- [x] 3.1 In `app/services/chat.py`, add `ChatUnavailableError`. `generate_answer` raises it on any provider exception or an empty answer, logs only the exception type and HTTP status (when present) server-side, and keeps the provider's message out of the error. Add tests: a fake client that raises an exception whose message contains a secret-looking string makes `generate_answer` raise `ChatUnavailableError`, and `str(err)` doesn't contain that string. Verify: `pytest` passes.
- [x] 3.2 In `RAGService.answer_query`, catch `ChatUnavailableError` and build the extractive answer: the fixed lead sentence, then one `[chunk_id] text` paragraph per context block, with citations equal to the context ids. Replace the outer `except`'s `{str(e)}` text with the fixed "couldn't search the knowledge base" message. Add `answer_mode` (`generated`, `extractive`, `no_results` or `error`) to the result. Add `answer_mode: Literal[...]` to `DebugInfo`, and copy it in `app/main.py`.
  - Update the existing tests that compare `debug` exactly (`tests/test_api.py`, `tests/test_rag_service.py`).
  - Add tests: a rate-limit failure gives 200, `extractive`, citations `["returns#1", "shipping#1"]`, and no provider error text anywhere in the JSON body; a model answer gives `generated`; no results gives `no_results` with the model not called; an embedding failure with a secret-looking message gives 200, `error`, no citations, and no provider text in the body.

  Verify: `pytest` and `ruff check .` pass.

- [x] 3.3 Bound model calls (design Decision 10): add `OPENAI_TIMEOUT_SECONDS` (default 30) and `OPENAI_MAX_RETRIES` (default 1), and pass them to both OpenAI-compatible clients, so a hung free-tier call ends in the `extractive` fallback instead of a 10-minute wait. Verify: tests assert the clients' `timeout` and `max_retries` follow the settings, and `pytest` passes.

## 4. Admin token for seeding (spec: knowledge-base-seeding)

- [x] 4.1 Add the `seed_token` setting, where empty means unset, and a `require_seed_token` dependency attached to `/seed` only. It uses `HTTPBearer(auto_error=False)` and `hmac.compare_digest`, and returns 401 with `WWW-Authenticate: Bearer`. At startup, log a warning when `ENVIRONMENT=production` and no token is set. Add `SEED_TOKEN` to `.env.example` with a comment. Add tests in `tests/test_api.py`:
  - a missing or wrong token gives 401 and `seed_documents` is not awaited;
  - the correct token gives 200;
  - an unset or empty token leaves `/seed` open;
  - with a token configured, `/answer`, `/healthz`, `/documents` and `/` need no header.

  Verify: `pytest` passes.
- [ ] 4.2 In `static/chat.html`, the document-save handler:
  - sends `Authorization: Bearer <token>` when a token is in `sessionStorage`, with every storage access wrapped in try/catch;
  - on 401 with no stored token, calls `prompt()` for the token, stores it, and retries once;
  - on a second 401, clears the token and shows "Admin token rejected".

  Verify locally in a browser, with `SEED_TOKEN=local-test` in `.env` and the app on the task 1.1 Supabase project: the first save prompts; a wrong token shows the error and the next save prompts again; the right token saves; and with `SEED_TOKEN` unset, saving never prompts.
- [ ] 4.3 In `chatbot.py`, send `Authorization: Bearer $SEED_TOKEN` on `/seed` when the environment variable is set. Verify locally against the app with `SEED_TOKEN=local-test`: `python chatbot.py http://localhost:8000` then `/seed` fails with 401 without the variable, and succeeds with `SEED_TOKEN=local-test` set in the shell.

## 5. Render blueprint and deployment docs (spec: deployment)

- [x] 5.1 Add `render.yaml` per design Decision 8:
  - one `web` service, `runtime: docker`, `plan: free`, `dockerfilePath: ./Dockerfile`, `branch: main`, `healthCheckPath: /healthz`, `autoDeployTrigger: checksPass`, `region: singapore`;
  - non-secret Gemini settings with values; `sync: false` for the four secrets; `generateValue: true` for `SEED_TOKEN`;
  - no `PORT` entry.

  Verify: the file parses as YAML, `plan` is `free`, and no `envVars` entry carries a secret value. Grep for `key`, `secret` and `token` values to confirm.
- [ ] 5.2 Rewrite `DEPLOYMENT.md` as the free deployment guide:
  - Gemini key, Supabase project and schema (with the legacy `anon`/`service_role` key note), and New Blueprint in Render with the four prompted secrets;
  - where to find the generated `SEED_TOKEN`; seeding through the chat page or `chatbot.py <url>`;
  - cold starts and free-tier limits, the re-seed note, the Gemini free-tier data-use note, and changing secrets later in the Environment tab;
  - Cloud Run reduced to a short "paid alternative" note.

  Add a "Deploy to Render" button and a link to `DEPLOYMENT.md` in the README. Verify: every command and setting name in `DEPLOYMENT.md` matches `render.yaml` and `.env.example`, checked by grep, and task 6.2 follows it as written.

## 6. Deploy and verify end to end (owner + implementer)

- [ ] 6.1 Merge this change to `main` through a pull request whose `lint`, `test` and `docker-build` checks are green. Verify: the CI run on `main` passes.
- [ ] 6.2 Owner follows `DEPLOYMENT.md`: in Render, choose New Blueprint, pick the GitHub repo, review the preview, enter the four secrets, and apply. Verify:
  - the preview shows exactly one free web service built from `./Dockerfile`;
  - no payment method is requested;
  - the first deploy goes live after the CI checks on `main`;
  - `GET https://<service>.onrender.com/healthz` returns `{"status": "ok", "database_connected": true}`.
- [ ] 6.3 On the deployed URL:
  - `POST /seed` without a token returns 401;
  - saving the default documents in the chat page prompts for the `SEED_TOKEN` from the Render dashboard, then succeeds;
  - a question about returns gets an answer with citations and `debug.answer_mode: "generated"`.

  Verify by recording the `/answer` JSON.
- [ ] 6.4 Exercise the fallback in production: temporarily set `OPENAI_CHAT_MODEL` to a non-existent model in the Render Environment tab, ask a question, then restore the value. Verify: the answer has `debug.answer_mode: "extractive"`, cites the retrieved chunks, and has no provider error text; after the restore, `generated` returns.

## Workflow follow-up

- Archive `add-github-actions-ci` first, then this change, so that the main specs (`continuous-integration`, `model-provider`, `question-answering`, `knowledge-base-seeding`, `deployment`) are created in order.
- If `region: singapore` doesn't suit the owner, change it in `render.yaml` before task 6.2. Render can't change it after the service is created.
