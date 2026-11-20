# Design

## Context

See proposal.md for motivation and specs/ for the required behavior.

Current state that shapes the approach:

- `/answer` runs `RAGService.answer_query` (`app/services/rag.py`). It embeds the question with `EmbeddingService.embed_texts` (the sync `openai` client pointed at Gemini's OpenAI-compatible endpoint), calls `db.vector_search` (Supabase RPC), then `ChatService.generate_answer` (the same `openai` client, or `anthropic`). Every outcome already ends in `debug.answer_mode`.
- `/seed` runs `RAGService.seed_documents`: chunk, embed in batches of `EMBEDDING_BATCH_SIZE`, `db.upsert_chunks`, `db.delete_chunks_except`.
- Provider error text is deliberately kept out of responses: `ChatService` raises `ChatUnavailableError(...) from None` and logs only the error type and HTTP status.
- The service runs on Render's free plan: one Docker container, 512 MB RAM, 0.1 CPU, `uvicorn` started directly by the Dockerfile `CMD`. There is no room for a Datadog Agent sidecar.
- Settings come from `pydantic-settings` (`app/core/config.py`). Service objects are module-level singletons built at import.
- Tests (`tests/conftest.py`) overwrite the environment with placeholder settings before importing `app`, and an autouse fixture replaces every external client with one that fails the test if used.

Facts about Datadog Agent Observability, from Datadog's docs in November 2026:

- The Free plan is $0 and includes up to 40K LLM spans a month with 15-day retention. Only LLM spans are metered. Workflow, task, embedding and retrieval spans are reported as free, but only the product page says so.
- The Python SDK (`ddtrace`) supports agentless mode (`agentless_enabled=True` with `api_key` and `site`), enabled in code with `LLMObs.enable(...)`. Datadog says not to combine that with `ddtrace-run`.
- The SDK's `openai` auto-instrumentation lists chat completions, completions and responses for Python, but not `embeddings.create()`. Nothing says how it labels Gemini behind a custom `base_url`.
- Span kinds: `workflow`, `agent`, `task`, `tool`, `llm`, `embedding`, `retrieval`. `LLMObs.annotate` sets input, output, metadata, metrics (`input_tokens`, `output_tokens`, `total_tokens`) and tags. `LLMObs.flush()` sends buffered spans and blocks until done.

## Goals / Non-Goals

**Goals:**
- One trace per `/answer` and per `/seed`, with a span shape that reads like the pipeline: workflow, embedding, retrieval, llm.
- Zero runtime cost and zero Datadog import when tracing is off. That covers tests, CI, local development without a key, and production before the owner adds a key.
- Every tracing decision in one module: on/off, text capture, error sanitizing, provider labels. Services only say "this step started, this is what it took and returned".
- Offline tests that check span shape and redaction with a test double.

**Non-Goals:**
- APM traces, the Datadog Agent, metrics, log forwarding, dashboards, monitors, Datadog evaluations or experiments.
- Visitor sessions or user IDs. The chat page has no identity, so no session or user tags are sent.
- Changing the sync `openai` client or any request/response contract.

## Decisions

### 1. Manual spans through the SDK, enabled in code, with auto-instrumentation off

`app/core/observability.py` calls `LLMObs.enable(ml_app=..., api_key=..., site=..., agentless_enabled=True, integrations_enabled=False, env=..., service=...)` once at startup. Our own code opens every span. The Dockerfile `CMD` stays plain `uvicorn`.

Why:
- Agentless is the only option on a single free container.
- With integrations on, the `openai` integration would add its own LLM span inside ours. That doubles the metered spans and breaks the "exactly one LLM span" requirement. With integrations off, every span is deliberate.
- Auto-instrumentation alone gives neither the embedding step (not listed for Python) nor retrieval (Supabase RPC) nor the request-level workflow span. Manual spans give the exact shape the spec asks for, the same for `openai` and `anthropic`, and are testable with a fake.

Alternatives considered:
- `ddtrace-run` or `import ddtrace.auto` with auto-instrumentation. This also starts APM and patches every library, and it still misses embedding and retrieval.
- OpenTelemetry with export to Datadog. It needs an Agent or Collector, or OTLP intake setup, and the LLM span semantics (messages, token metrics) are less direct.
- A different free LLM tracing tool. The owner asked for Datadog.

### 2. A thin wrapper with a swappable recorder

Services call only the wrapper:

```text
observability.setup(settings) -> bool               # once, in the app lifespan
with observability.workflow("answer_question") as span: ...
with observability.embedding("embed_texts", model=..., provider=...) as span: ...
with observability.retrieval("vector_search") as span: ...
with observability.llm("chat_completion", model=..., provider=...) as span: ...
with observability.task("save_chunks") as span: ...
span.record(input=..., output=..., metadata=..., metrics=..., tags=...)
span.fail(error_type, http_status=None)
observability.current_trace_id() -> str | None
observability.flush()
```

Behind it sits a recorder: `NoopRecorder` (the default), `DatadogRecorder` (wraps `LLMObs`) and, in tests, `FakeRecorder`, which records span dicts with kind, name, parent, fields and error. `ddtrace` is imported only inside `DatadogRecorder`, and only when `setup` decides tracing is on. With tracing off, the context managers are cheap no-ops and `ddtrace` is never loaded. That keeps memory flat on the 512 MB instance and keeps tests free of the SDK.

Checked against `ddtrace` 4.17.2 (task 1.2):
- `LLMObs.enable` accepts every argument listed in Decision 1.
- `LLMObs.llm` and `LLMObs.embedding` take `model_name=` and `model_provider=`. `workflow`, `retrieval` and `task` take `name=`.
- Each of these returns a span used as a context manager, and its `__exit__` records `str(exc)` and the stack (see Decision 4).
- `LLMObs.export_span()` returns `{"span_id", "trace_id"}` with the Agent Observability trace ID.

Alternative: put `@workflow`/`@llm` SDK decorators straight on service methods. That spreads SDK calls across services, applies the SDK even when tracing is off, and can't enforce text capture or error sanitizing in one place.

### 3. Where each span is opened

| Request | Span (kind, name) | Opened in | Records |
|---|---|---|---|
| `/answer` | workflow `answer_question` | `RAGService.answer_query`, around the whole body | input: question; output: answer text; metadata: `top_k`, `answer_mode`, citations, latency; tag `answer_mode` |
| | embedding `embed_texts` (one per batch) | `EmbeddingService.embed_texts`, around each request | model, provider, input documents, dimensions, output summary ("1 vector × 1536") |
| | retrieval `vector_search` | `RAGService.answer_query`, around `db.vector_search` | input: question, `top_k`; output: documents `{id: chunk_id, name: title, score: similarity, text}` |
| | llm `chat_completion` | `ChatService.generate_answer`, around the provider call and its error handling | model, provider, system and user messages, assistant message, `temperature`, `max_tokens`, token metrics from `usage` |
| `/seed` | workflow `seed_knowledge_base` | `RAGService.seed_documents` | metadata: documents, chunks, inserted, removed |
| | embedding `embed_texts` (per batch) | as above | as above |
| | task `save_chunks`, task `delete_old_chunks` | `RAGService.seed_documents`, around the two `db` calls | counts |

The retrieval span lives in `rag.py`, not `database.py`, because document titles come from `DOCUMENT_TITLES` in `rag.py` and tests already swap the database for a fake. Nesting relies on the SDK's context-variable tracking of the active span. All steps of one request run in the same asyncio task, so parent and child links hold across `await`.

### 4. Errors are recorded by type and HTTP status, never by message

The SDK's span context manager records `str(exc)` when an exception passes through it. Provider messages can echo request or account details, which this project already keeps out of responses and logs. So the wrapper catches an exception inside the span, marks the span as an error with only `type(exc).__name__` and the `status_code` attribute when there is one, closes the span, and re-raises after the span has closed. `ChatService` calls `span.fail(type, status)` in its existing `except` block, so the original error type and status (e.g. `RateLimitError`, 429) are recorded rather than the sanitized `ChatUnavailableError`.

### 5. Text capture is enforced in the wrapper

`OBSERVABILITY_CAPTURE_TEXT` (default `true`) is read once by `setup`. When it is `false`, `span.record` replaces every text value before it reaches the recorder: message content becomes `"[text omitted: N chars]"`, the question becomes `{"question_chars": N}`, and retrieval documents keep `id`, `name` and `score` but drop `text`. Because services always pass text through `record`, they can't bypass the switch. Secrets need no filter: no span field is ever built from settings, headers or cookies, and a test checks that.

### 6. Configuration

New `Settings` fields, read from the environment like the existing ones:

| Variable | Default | Meaning |
|---|---|---|
| `DD_API_KEY` | empty | Datadog API key. Empty means tracing is off. |
| `DD_SITE` | `datadoghq.com` | Datadog site, from the account's URL (e.g. `ap1.datadoghq.com`). |
| `DD_LLMOBS_ML_APP` | `yt-rag` | Application name shown in Datadog. |
| `OBSERVABILITY_ENABLED` | `true` | Set `false` to turn tracing off while keeping the key. |
| `OBSERVABILITY_CAPTURE_TEXT` | `true` | Set `false` for metadata-only traces. |

The environment tag comes from the existing `ENVIRONMENT`. The version comes from `RENDER_GIT_COMMIT`, which Render sets automatically, when it is present. Before importing `ddtrace`, `setup` does `os.environ.setdefault(...)` for `DD_VERSION` (from `RENDER_GIT_COMMIT`), `DD_APM_TRACING_ENABLED=false`, `DD_REMOTE_CONFIGURATION_ENABLED=false` and `DD_INSTRUMENTATION_TELEMETRY_ENABLED=false`. In `ddtrace` 4.17.2, `DD_APM_TRACING_ENABLED=false` selects the `LLMOBS_AGENTLESS` export mode, in which spans go straight to the intake and no APM traces are sent. Without it, the SDK picks `APM_AGENTLESS` and ships APM traces as well. Agentless mode already moves telemetry and remote config to the intake, so turning those two off only removes background traffic. `setdefault` lets the owner override any of them.

`DD_LLMOBS_ENABLED` is deliberately not the switch: with the API key as the switch, the owner sets one value to turn tracing on. The SDK reads `DD_API_KEY` and `DD_SITE` itself too, which is harmless because we pass the same values explicitly.

### 7. Lifecycle

- Startup: `observability.setup(settings)` runs first in the app lifespan, before the database connects. Any exception there is caught and logged as one warning, and the recorder stays `NoopRecorder`. One info line names the site and app, never the key.
- Shutdown: the lifespan calls `observability.flush()` after `db.disconnect()`, inside `try/except`. Render sends SIGTERM on deploys and when the free instance spins down, and uvicorn runs the lifespan shutdown on SIGTERM.
- Request path: the SDK buffers spans and sends them from a background thread, so requests never wait on Datadog.

### 8. Trace ID in the server log

Inside the workflow span, `answer_query` writes one log line for every outcome: `Answer finished: mode=<answer_mode> latency=<ms>ms trace_id=<id>`. The ID comes from `LLMObs.export_span()`, and `trace_id=` is left out when tracing is off. This replaces the current "Query processed in ..." line in `rag.py`, which was only written for generated answers.

### 9. Dependency

Add `ddtrace>=4.12,<5` to `requirements.txt`, pinned to the latest 4.x release at implementation time. 4.x is the line the current docs describe, and the upper bound guards against SDK API changes. The image grows by the size of the wheel. Runtime memory grows only when tracing is on, because of the lazy import.

### 10. Tests

- `tests/conftest.py` adds `DD_API_KEY=""` and `OBSERVABILITY_ENABLED=false` to the placeholder settings. An autouse fixture makes `DatadogRecorder` creation fail the test, mirroring `_ForbiddenClient`.
- `tests/test_observability.py` installs a `FakeRecorder` and drives the existing fakes (embedding service, database, chat client) through each spec scenario: span shape and order, outcomes, exactly one LLM span, error type and status without the message, text capture off, no secrets in any recorded value, the same `/answer` response with the noop and fake recorders, tags, trace ID in the log, and flush on `TestClient` exit.
- `setup` tests monkeypatch the SDK entry point to capture the arguments: agentless on, integrations off, site, app, env. They also check that an exception during setup leaves the app serving with tracing off. No test opens a network connection.

## Risks / Trade-offs

- [The free plan's terms or the card requirement change, or sign-up asks for a card] → Tracing is optional and off by default. The guide tells the owner to stop if a card is requested, and the app is unaffected.
- [Visitor questions and answers are stored at Datadog for 15 days] → `OBSERVABILITY_CAPTURE_TEXT=false` gives metadata-only traces, and the guide states the data flow. These questions already go to Gemini's free tier, which may use them.
- [The SDK records exception messages or other content we didn't intend] → Integrations are off, so only our spans exist. Errors are recorded by type and status (Decision 4). The fake-recorder tests check the redaction. One manual check of a real trace is in the tasks.
- [The SDK still tries to reach a local Agent (APM, remote config, telemetry) and fills the log] → `setdefault` of the three env vars before import (Decision 6), plus a local run with no Agent and a check that the log has no `localhost:8126` or Agent connection errors.
- [SDK API details differ by version, e.g. `model_name` vs `model`, or `enable()` arguments] → Pin to one major line, keep SDK calls inside `DatadogRecorder`, and check signatures against the installed version while implementing.
- [Extra memory or CPU on the 512 MB / 0.1 CPU instance] → Lazy import, background sending, a few spans per request. Measure RSS with tracing on in the local container before merging, and turn tracing off if it threatens the limit.
- [A public page gets spammed past 40K LLM spans] → Gemini's free daily limit stops answering long before that. Without a payment method there is nothing to bill, so Datadog drops the excess.
- [Datadog shows estimated costs at Gemini list prices although the free tier is used] → Cosmetic. The guide mentions it.
- [Adding `sync: false` variables to an existing blueprint doesn't prompt for values] → The guide's existing-service path sets `DD_API_KEY` and `DD_SITE` in the Environment tab.

## Migration Plan

1. Merge to `main`. CI passes offline, and Render deploys with `DD_API_KEY` empty, so tracing is off and behavior is unchanged.
2. The owner signs up for Datadog on the free plan, notes the site from the app URL, and creates an API key under Organization Settings → API Keys.
3. In Render → `yt-rag` → Environment, the owner sets `DD_API_KEY` and `DD_SITE` and saves, which redeploys.
4. The owner asks a question on the live page and opens Datadog → AI Observability (Agent Observability) → Traces, filtered by `ml_app:yt-rag`.

Rollback: set `OBSERVABILITY_ENABLED=false` or clear `DD_API_KEY` in Render, which needs no code change. Or revert the commit.

## Open Questions

- Whether the ID returned by `LLMObs.export_span()` can be pasted directly into the Datadog trace search or needs a different format. This is settled during the manual check; the spec only requires that the log line carries an ID that finds the trace.
