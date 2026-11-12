# Design

## Context

See `proposal.md` for motivation and `specs/` for the required behaviour. These facts shape the approach.

**Current code** (on the `add-github-actions-ci` branch):
- `EmbeddingService` creates `openai.OpenAI(api_key=...)`, sends every text in one request, and returns whatever size the provider gives.
- `ChatService` catches every provider error and *returns* `"I encountered an error ... {str(e)}"` as the answer, which leaks provider details.
- `/seed` has no authentication. The chat page's document editor (`static/chat.html`) is the only browser caller of `/seed`.
- `chatbot.py` takes the API URL as its first argument.
- Settings are read once, at import time, from environment variables and `.env`.
- The `embedding_dimensions = 1536` setting exists but is unused.

**Supabase schema:** `rag_chunks.embedding` is `VECTOR(1536)`, with an IVFFlat cosine index. `match_chunks` orders by cosine distance (`<=>`). pgvector can't index plain `vector` columns above 2000 dimensions.

**Gemini, from the official docs** (researched 2026-11-12):
- The OpenAI-compatible base URL `https://generativelanguage.googleapis.com/v1beta/openai/` supports chat completions and `embeddings.create`.
- The docs' examples use `gemini-3.8-flash` for chat and `gemini-embedding-2` for embeddings.
- Embeddings default to 3072 dimensions. The native API reduces this with `output_dimensionality`, and `gemini-embedding-2` renormalizes reduced outputs.
- The OpenAI-compatible page doesn't say whether the OpenAI `dimensions` parameter is honoured, or whether list inputs are accepted. The layer is labelled beta.

**Render, from the official docs:**
- The free web service has 512 MB RAM and 0.1 CPU, and 750 hours a month.
- It spins down after 15 minutes without traffic and takes about a minute to start again. The local filesystem is lost when it spins down.
- No payment method is needed. Docker builds are supported.
- `PORT` defaults to 10000, and the service must bind to `0.0.0.0`.
- The blueprint (`render.yaml`) supports `runtime: docker`, `plan: free`, `healthCheckPath`, and `autoDeployTrigger: checksPass` (deploy only after the GitHub checks pass).
- `envVars` entries with `sync: false` are prompted for only when the blueprint is first created. `generateValue: true` makes Render create a random 256-bit value.

**Dockerfile:** `CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}` already honours `PORT`.

## Goals / Non-Goals

**Goals:**
- Run the whole RAG flow (seed → embed → search → answer) on free tiers, with only configuration changes between OpenAI and Gemini.
- Keep local development and the existing OpenAI path working unchanged when the new settings are unset.
- Keep the Supabase schema unchanged.

**Non-Goals:**
- Separate endpoints or keys for chat and embeddings (e.g. Groq chat with Gemini embeddings). One base URL serves both.
- Rate limiting or authentication on `/answer`.
- Making the service always-on (paid plans) or adding keep-alive pings.
- Local or in-container embedding models (512 MB RAM is too tight).
- Moving off the synchronous OpenAI client, changing CORS, or slimming the Docker image.
- Migrating data embedded with another model (re-seeding is the documented path).

## Decisions

### 1. Keep the `OPENAI_*` setting names and add `OPENAI_BASE_URL`
- **What:** add `openai_base_url: Optional[str] = None` to `Settings`. Pass it explicitly as `base_url=` to `openai.OpenAI(...)` in both `EmbeddingService` and `ChatService`. With Gemini, `OPENAI_API_KEY` holds the Gemini key.
- **Why pass it explicitly:** the OpenAI SDK reads the `OPENAI_BASE_URL` environment variable by itself, but not values that pydantic-settings loads from `.env`. Passing it explicitly also makes it testable.
- **Unset value:** when the setting is unset or empty, pass `DEFAULT_OPENAI_BASE_URL` (`https://api.openai.com/v1`), not `None`. With `None`, the SDK falls back to the raw environment variable, and an empty `OPENAI_BASE_URL=` produced a client with base URL `''` (verified with the installed SDK).
- **Why reuse the names:** existing `.env` files, `DEPLOYMENT.md` and the tests keep working. "OpenAI-compatible" is the protocol the code speaks.
- **Rejected:** new provider-neutral names (`LLM_BASE_URL`, `LLM_API_KEY`, ...). They are clearer, but break every existing configuration for no functional gain. They can be added later as aliases.
- **Rejected:** a dedicated `gemini` provider using Google's SDK. It adds a dependency and a second code path.

### 2. Model defaults stay provider-neutral in code
- **What:** code defaults remain `gpt-4o` and `text-embedding-3-small`. The Gemini values (`gemini-3.5-flash`, `gemini-embedding-2`, the base URL) live only in `render.yaml` and as a documented block in `.env.example`.
- **Why:** an unset configuration behaves exactly as today. Swapping providers is purely a configuration change.
- **Chat model chosen by probing (2026-11-12, owner's free-tier key):**
  - `gemini-3.8-flash`, the model in Google's doc examples, returned HTTP 503 on every attempt.
  - `gemini-3.7-flash` and `gemini-flash-latest` timed out after 30 s, and `gemini-2.5-flash` returned 404.
  - `gemini-3.5-flash` answered correctly in about 3 s, with the citation, so it is the configured default.
  - Free-tier model availability changes. Switching the model is a one-line `OPENAI_CHAT_MODEL` change.

### 3. Enforce the embedding size on the client
- **Request:** every embedding request passes `dimensions=EMBEDDING_DIMENSIONS`.
- **Enforce:** each returned vector is checked.
  - Equal length: used as is.
  - Longer: the first `EMBEDDING_DIMENSIONS` values are kept, then L2-normalized.
  - Shorter: a `ValueError` naming both sizes is raised. Because embedding happens before any write, nothing is stored.
- **Why truncation is safe:**
  - Gemini embedding models are trained so that leading prefixes are valid lower-dimensional embeddings. That is what `output_dimensionality` relies on.
  - `gemini-embedding-2` renormalizes reduced outputs, and the normalization step does the same.
  - Cosine search is scale-invariant in any case.
- **Why keep `VECTOR(1536)`:** it stays indexable (3072 is not), and no Supabase migration is needed.
- **Unknowns:** whether Gemini's OpenAI layer honours or rejects `dimensions` is undocumented. Task 1.2 settles it with one real request. If Gemini *rejects* the parameter, an `EMBEDDING_SEND_DIMENSIONS` setting (default `true`) turns it off and truncation alone applies. If Gemini ignores it, nothing changes.
- **Rejected:** a `halfvec(3072)` column (schema migration, larger index), or the native Gemini API with `output_dimensionality` (new SDK, provider lock-in).
- **Verified 2026-11-12 (task 1.2, `gemini-embedding-2` via the OpenAI-compatible endpoint):**
  - `dimensions=1536` is **honoured**: vectors come back with 1536 values, already unit-length.
  - Without it, they come back with 3072.
  - So `EMBEDDING_SEND_DIMENSIONS=true` stays, and truncation is only a safety net.
  - Gemini omitted `index` on the first item (`[None, 1, 2]`). `embed_texts` re-sorts only when every item has an integer index, so it keeps the response order.

### 4. Batch embedding requests
- **What:** `embed_texts` splits its input into slices of `EMBEDDING_BATCH_SIZE` (default 100), sends one request per slice, and concatenates the results in order.
- **Why 100:** the documented OpenAI-compatible example sends a single string. 100 is a conservative cap for list inputs on Gemini.
- **Verification:** task 1.2 checks that a list input of several texts works. If it doesn't, the documented setting for Gemini becomes `EMBEDDING_BATCH_SIZE=1`; 4 default chunks means 4 requests, well within the free per-minute limit.
- **Verified 2026-11-12:** a list of 3 texts returned 3 embeddings in one request, and a single string also works. `EMBEDDING_BATCH_SIZE=100` stays.

### 5. Chat failures raise; RAG builds the fallback answer
- **ChatService:** `ChatService.generate_answer` stops returning error text. On any provider exception, or an empty answer, it logs the error type and HTTP status (e.g. `RateLimitError (HTTP 429)`) server-side, and raises `ChatUnavailableError` without the provider's message. The status tells a used-up quota apart from a wrong model name in the Render logs, without logging provider text.
- **RAGService:** `RAGService.answer_query` catches `ChatUnavailableError` and builds the extractive answer from the already deduplicated context blocks (at most 4):
  - A fixed lead sentence: "A generated answer isn't available right now. Here are the most relevant passages:"
  - Then one `[chunk_id] text` paragraph per block.
  - `citations` lists the context chunk ids in order.
- **`answer_mode`:**
  - `generated`: the model answered.
  - `extractive`: the fallback built the answer.
  - `no_results`: retrieval found nothing. This is the existing early-return path, and the model is not called.
  - `error`: answering failed before the model was called, for example when embedding the question raised.
- **Retrieval failures:** the outer `except` in `answer_query` returns the fixed text "I couldn't search the knowledge base right now. Please try again shortly.", with no citations. The exception type goes to the server log. The old `{str(e)}` text is removed.
- **Known limitation:** `db.vector_search` already swallows its own errors and returns `[]`, so a Supabase outage *during search* surfaces as `no_results`, not `error`. Changing the database layer is outside this change.
- **Plumbing:** `answer_mode` is added to `DebugInfo` as a `Literal`, and `app/main.py` copies it into the response.
- **Why in RAG, not ChatService:** the fallback needs the retrieved context and citation logic, which RAGService owns. ChatService stays a thin provider adapter.
- **Rejected:** keeping error strings as answers. That leaks provider details, and clients can't tell a failure from an answer.

### 6. Bearer-token dependency on `/seed`
- **What:** `seed_token: Optional[str] = None` is a new setting; an empty string is treated as unset.
- **FastAPI dependency:** `require_seed_token` reads the `Authorization: Bearer` header through `HTTPBearer(auto_error=False)`. When a token is configured, it compares with `hmac.compare_digest` and raises 401 with `WWW-Authenticate: Bearer` on a missing or wrong token. The dependency is attached to `/seed` only.
- **Order of checks:** the token is checked before the request body is processed, so no embedding call or write happens on 401.
- **Startup warning:** at startup, if `ENVIRONMENT=production` and no token is set, a warning is logged.
- **Rejected:** a custom `X-Admin-Token` header (non-standard), HTTP Basic auth (needs a username for no benefit), and protecting every endpoint (the owner chose to keep `/answer` open for testing).

### 7. Chat page and CLI send the token
- **`static/chat.html`:**
  - The save handler sends `Authorization: Bearer <token>` when a token is held in `sessionStorage`; every storage access is wrapped in try/catch.
  - On 401 with no stored token, it calls `prompt()`, stores the answer, and retries once.
  - On a second 401, it clears the stored token and shows "Admin token rejected".
  - `sessionStorage` keeps the token for the tab only.
  - **Rejected:** a permanent token input field (more UI, for a feature only the owner uses).
- **`chatbot.py`:** reads `os.environ.get("SEED_TOKEN")` and adds the header to its `/seed` request when set. A deployed instance is targeted with `python chatbot.py https://<service>.onrender.com`.

### 8. Render blueprint (`render.yaml`)
- **Service:** one `type: web` service named `yt-rag`, with `runtime: docker`, `plan: free` (set explicitly, because omitting it selects a paid plan), `dockerfilePath: ./Dockerfile`, `branch: main`, `healthCheckPath: /healthz`, `autoDeployTrigger: checksPass` and `region: singapore` (see Open Questions).
- **`envVars`:**
  - **Values set:** `AI_PROVIDER=openai`, `OPENAI_BASE_URL`, `OPENAI_CHAT_MODEL=gemini-3.5-flash`, `OPENAI_EMBED_MODEL=gemini-embedding-2`, `EMBEDDING_DIMENSIONS=1536`, `ENVIRONMENT=production`.
  - **`sync: false`, prompted when the blueprint is created:** `OPENAI_API_KEY`, `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`.
  - **`generateValue: true`:** `SEED_TOKEN`.
- **Port:** no `PORT` entry is set; the Dockerfile already binds `${PORT}`.
- **Health check:** `/healthz` returns 200 once the app is up (even when degraded) and fails if startup fails. Startup fails when settings are missing or the Supabase client can't be created.
- **Rejected:** dashboard-only setup (not reproducible or reviewable), and Hugging Face Spaces (Docker Spaces now need the paid PRO plan).

### 9. Tests stay offline
The new behaviour is tested at the existing seams:
- fake OpenAI client objects inside `EmbeddingService` and `ChatService`;
- `TestClient` with the token configured or unset through monkeypatched settings.

`tests/conftest.py` also sets placeholder values for every new setting (`OPENAI_BASE_URL` unset, `SEED_TOKEN` empty, `EMBEDDING_DIMENSIONS`, `EMBEDDING_BATCH_SIZE`), so a developer's `.env` can't change test behaviour.

### 10. Bounded request time for model calls
- **What:** both OpenAI-compatible clients get `timeout=OPENAI_TIMEOUT_SECONDS` (default 30) and `max_retries=OPENAI_MAX_RETRIES` (default 1). A model call therefore gives up after about a minute at most, instead of the SDK default of 600 s with 2 retries.
- **Why:** the probe showed free-tier models *hanging*, not just erroring. A hung chat call isn't a failure until it times out, so without a bound the `extractive` fallback would never trigger in practice.
- **Rejected:** no retries at all. One retry absorbs the brief 503s seen on the free tier.

## Risks / Trade-offs

- **[Risk] The Gemini OpenAI layer is beta.** `dimensions` or list inputs may be ignored or rejected. → Task 1.1 checks this before any code is written. Truncation and the batch-size and send-dimensions settings cover every outcome without code changes.
- **[Risk] Free-tier quotas (Gemini per-minute and daily limits) run out during testing.** → `/answer` falls back to cited passages instead of failing. Seeding 4 default chunks costs one embedding request.
- **[Risk] Gemini's free tier may use prompts and documents to improve Google products.** → The documentation says so and advises seeding only non-sensitive documents.
- **[Risk] New Supabase projects may show new-format API keys that the pinned `supabase` client doesn't accept.** → The deploy task checks `/healthz`. If it fails, the docs point to the project's legacy `anon` and `service_role` keys.
- **[Risk] Free-plan resources are limited.**
  - Render sleeps after 15 minutes idle (about a 1-minute cold start), has 512 MB RAM, and can restart at any time.
  - Supabase free projects pause after a period of inactivity.
  
  → This is acceptable for testing and is documented. The app keeps no state on local disk.
- **[Trade-off] `OPENAI_API_KEY` holds a Gemini key.** → This is documented in `.env.example`, `render.yaml` comments and `DEPLOYMENT.md`.
- **[Trade-off] Embeddings from different models can't be compared.** → Documented: after switching `OPENAI_EMBED_MODEL`, re-seed every document (seeding upserts by `chunk_id`).
- **[Risk] `sync: false` secrets are prompted only when the blueprint is first created.** → The docs explain changing them later in the Render dashboard's Environment tab.

## Migration Plan

1. Merge `add-github-actions-ci` first, so `checksPass` has CI checks to wait for. Then implement this change on a branch from `main` and merge it once CI is green.
2. Owner setup, all free:
   - create a Gemini API key in Google AI Studio;
   - create a Supabase project and run `sql/init_supabase.sql`;
   - in Render, create a **New Blueprint** from the GitHub repo and fill in the four prompted secrets.
3. After the first green deploy:
   - copy `SEED_TOKEN` from the Render dashboard;
   - seed the default documents through the chat page;
   - ask a question and confirm `debug.answer_mode`.

**Rollback:** suspend or delete the Render service. Locally, unsetting `OPENAI_BASE_URL` and `SEED_TOKEN` restores the previous behaviour exactly. The Supabase schema is untouched.

## Open Questions

- **Region:** `region: singapore` assumes the owner is in Southeast Asia, and that the Supabase project should be created in the matching region (ap-southeast-1). Render can't change a service's region after creation, but the owner can edit this value in `render.yaml` before the first deploy, with no other impact.
