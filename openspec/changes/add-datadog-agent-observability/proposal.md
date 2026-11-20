# Proposal

## Why

When an answer on the live profile page is wrong, slow or falls back to raw passages, the only record is a few Render log lines: we can't see which passages were retrieved, what prompt Gemini received, what it returned, or which step took the time. Datadog Agent Observability (formerly LLM Observability) records each request as a trace of its operations, and its Free plan costs $0 (up to 40K LLM spans a month, 15-day retention). That fits the project's no-paid-services rule.

## What Changes

- Add optional tracing to Datadog Agent Observability for the deployed web app. It is off unless a Datadog API key is configured, and the app behaves exactly as today when it is off.
- Each `/answer` request becomes one trace: a workflow span for the request, with child spans for embedding the question, the vector search (retrieved chunk IDs and scores), and the chat model call (model, prompt, answer, token counts). The workflow span also records the outcome (`generated`, `extractive`, `no_results` or `error`). Each `/seed` becomes one trace of its chunking, embedding batches and database writes.
- Traces include question, passage and answer text by default. One setting switches to metadata only. API keys, the admin token and session cookies are never sent.
- Tracing runs without a Datadog Agent process ("agentless"), because Render's free plan runs one container. Datadog being unreachable, slow or rejecting the key never fails or noticeably slows a request.
- Exactly one LLM span is recorded per chat model call, so the Free plan's 40K LLM spans a month covers far more traffic than Gemini's free daily limits allow.
- Add the `ddtrace` package. The Render blueprint gets the non-secret Datadog settings plus an empty `DD_API_KEY` for the owner to fill in. Setup steps (free sign-up, choosing a Datadog site, creating an API key, finding traces) go into the deployment guide.
- Tests and CI stay offline. They never send data to Datadog and need no Datadog account.

Out of scope: the orchestrator CLI (a possible follow-up change), APM, infrastructure metrics, log forwarding, dashboards and monitors, and any change to the `/answer` or `/seed` responses.

## Capabilities

### New Capabilities
- `observability`: tracing of the web app's question-answering and seeding pipelines to Datadog Agent Observability. Covers how it is turned on and off, what each trace contains, what text and secrets are excluded, and how failures stay isolated from requests.

### Modified Capabilities
- `deployment`: the blueprint and deployment guide gain Datadog settings and free setup steps. This capability comes from the not-yet-archived `deploy-render-with-gemini` change, so the delta only adds requirements.

## Impact

- Code: new `app/core/observability.py`; spans added in `app/services/rag.py` (request, retrieval and database-write spans), `app/services/embedding.py` and `app/services/chat.py`; startup and shutdown hooks in `app/main.py`; new settings in `app/core/config.py`.
- Dependencies: `ddtrace` added to `requirements.txt`. The Docker image grows and memory use rises a little when tracing is on, which matters on Render's 512 MB free instance.
- Config and docs: `render.yaml`, `.env.example`, `DEPLOYMENT.md`, `README.md`.
- Tests: `tests/conftest.py` forces tracing off. New tests in `tests/test_observability.py` use a fake recorder.
- External: the owner signs up for Datadog themselves (free plan, no payment method) and pastes the API key into Render. Datadog's pages don't say whether sign-up asks for a card, so the guide tells the owner to stop if it does. Visitor questions and answers are stored at Datadog for 15 days unless text capture is turned off.
