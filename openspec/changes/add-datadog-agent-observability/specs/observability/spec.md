# Spec Delta

## Purpose

Records what the web app did for each question and each knowledge-base seed as a trace in Datadog Agent Observability, so the owner can see which steps ran, what they received and returned, how long they took, and where they failed, without affecting visitors.

## ADDED Requirements

### Requirement: Tracing is off unless a Datadog API key is configured
The application SHALL send nothing to Datadog unless `DD_API_KEY` is set to a non-empty value and `OBSERVABILITY_ENABLED` is not `false`. `OBSERVABILITY_ENABLED` defaults to `true`, so setting the API key alone turns tracing on.

#### Scenario: No API key
- **GIVEN** `DD_API_KEY` is unset or empty
- **WHEN** the application starts and answers questions
- **THEN** no data is sent to Datadog, no Datadog-related warning or error is logged per request, and the application behaves as it did before this change

#### Scenario: Turned off with a key present
- **GIVEN** `DD_API_KEY` is set and `OBSERVABILITY_ENABLED` is `false`
- **WHEN** the application answers a question
- **THEN** no data is sent to Datadog

#### Scenario: Turned on
- **GIVEN** `DD_API_KEY` is set and `OBSERVABILITY_ENABLED` is unset
- **WHEN** the application starts
- **THEN** tracing is on and the startup log says that traces are sent to the configured Datadog site, without printing the API key

### Requirement: Traces go directly to the configured Datadog site
When tracing is on, the application SHALL send traces directly to the Datadog site named in `DD_SITE`, which defaults to `datadoghq.com`. It SHALL NOT need a Datadog Agent process running beside it.

#### Scenario: Single container with no Datadog Agent
- **GIVEN** `DD_API_KEY` is valid for the site `ap1.datadoghq.com` and `DD_SITE` is `ap1.datadoghq.com`
- **WHEN** a question is answered in a container with no Datadog Agent
- **THEN** its trace appears in Agent Observability on `ap1.datadoghq.com`, and the server log shows no errors about connecting to a local Datadog Agent

### Requirement: Each answered question is recorded as one trace
Each `/answer` request SHALL produce one trace. Its root span covers the whole request and records the outcome (`debug.answer_mode`), citations and latency. Its child spans, in order, are embedding the question, the vector search, and, when it runs, the chat model call.

#### Scenario: Generated answer
- **WHEN** a question is embedded, retrieval finds passages and the chat model returns an answer
- **THEN** the trace has a root span with outcome `generated` and the cited chunk IDs, and child spans for embedding, retrieval and the chat model call, in that order

#### Scenario: Nothing retrieved
- **WHEN** retrieval finds no passages
- **THEN** the trace has embedding and retrieval spans, no chat model span, and the root span's outcome is `no_results`

### Requirement: Chat model span records the model call
The chat model span SHALL record the model name, the provider (`google` for Gemini's endpoint, `openai`, `anthropic`, or `custom` for any other endpoint), the prompt messages sent, the answer returned, the temperature and token limit, and the input and output token counts when the provider reports them.

#### Scenario: Gemini answers and reports usage
- **GIVEN** the chat model is `gemini-3.5-flash` through Gemini's OpenAI-compatible endpoint
- **WHEN** the model answers and reports 812 prompt tokens and 95 completion tokens
- **THEN** the chat model span shows model `gemini-3.5-flash`, provider `google`, the system and user messages, the assistant answer, 812 input tokens and 95 output tokens

#### Scenario: Provider reports no usage
- **WHEN** the model answers without usage figures
- **THEN** the chat model span is recorded without token counts and the request is unaffected

### Requirement: Retrieval span records the retrieved passages
The retrieval span SHALL record the number of passages requested and, for each passage returned, its chunk ID, document title, similarity score and text.

#### Scenario: Two passages retrieved
- **WHEN** the vector search returns `skills#1` with score 0.82 and `experience#2` with score 0.77
- **THEN** the retrieval span lists both chunk IDs with those scores, their document titles and their text

### Requirement: Fallbacks and failures are visible in the trace
A failed step SHALL be marked as an error on its span, recording the error type and HTTP status when known but not the provider's error message. The root span SHALL still record the outcome the visitor received.

#### Scenario: Chat model fails and passages are returned
- **WHEN** the chat model request fails with a rate-limit error whose message contains provider details
- **THEN** the chat model span is marked as an error with the error type and HTTP status 429, the provider's message appears nowhere in the trace, and the root span's outcome is `extractive`

#### Scenario: Embedding the question fails
- **WHEN** embedding the question fails
- **THEN** the embedding span is marked as an error, no retrieval or chat model span follows, and the root span's outcome is `error`

### Requirement: Exactly one LLM span per chat model call
Each chat model request SHALL be recorded as exactly one LLM span, including a request that fails, and no other step SHALL be recorded as an LLM span. This keeps usage within Datadog's free monthly LLM span allowance.

#### Scenario: One generated answer
- **WHEN** one question is answered by the chat model
- **THEN** its trace contains exactly one LLM span

#### Scenario: Seeding
- **WHEN** the knowledge base is seeded
- **THEN** its trace contains no LLM spans

### Requirement: Each seed is recorded as one trace
Each `/seed` request SHALL produce one trace. The root span records the number of documents, the number of chunks, and the chunks inserted and removed. Child spans cover each embedding batch and the database writes. A failed seed marks the failing step and the root span as errors.

#### Scenario: Seeding the default documents
- **WHEN** the admin seeds the default documents and they produce 12 chunks with an embedding batch size of 100
- **THEN** the trace has one embedding span for the 12 chunks, spans for saving the chunks and deleting old ones, and a root span recording the document count, 12 chunks, and the inserted and removed counts

#### Scenario: Seeding fails while embedding
- **WHEN** embedding fails during a seed
- **THEN** the embedding span and the root span are marked as errors, and no database write spans follow

### Requirement: Text capture can be switched off
By default, traces SHALL include the visitor's question, the retrieved passage text, the prompt messages and the answer. When `OBSERVABILITY_CAPTURE_TEXT` is `false`, traces SHALL include none of that text, only its length, plus chunk IDs, scores, titles, model, timings, token counts, outcomes and errors.

#### Scenario: Default
- **WHEN** a visitor asks "What can Kai do?" with tracing on and `OBSERVABILITY_CAPTURE_TEXT` unset
- **THEN** the root span and the chat model span include the text "What can Kai do?"

#### Scenario: Text capture off
- **GIVEN** `OBSERVABILITY_CAPTURE_TEXT` is `false`
- **WHEN** a visitor asks "What can Kai do?"
- **THEN** the text "What can Kai do?" appears nowhere in the trace, and the root span records the question's length and the outcome

### Requirement: Secrets are never sent to Datadog
Traces MUST NOT contain the model API key, the Supabase keys, the Datadog API key, the admin token (`SEED_TOKEN`), the admin session cookie, or any request header value.

#### Scenario: Seeding with the admin token
- **WHEN** the admin seeds with `Authorization: Bearer <SEED_TOKEN>`
- **THEN** the token value appears nowhere in the trace

### Requirement: Tracing never breaks or slows requests
Requests SHALL succeed with the same responses whether Datadog is reachable or not and whether it accepts the API key or not. Traces SHALL be sent outside the request path. If tracing cannot start, the application SHALL start with tracing off and log one warning.

#### Scenario: Invalid API key
- **GIVEN** `DD_API_KEY` is set to a key Datadog rejects
- **WHEN** a visitor asks a question
- **THEN** `/answer` returns the same response it would with tracing off, and the rejection appears only in the server log

#### Scenario: Tracing fails to start
- **WHEN** starting tracing raises an error at application startup
- **THEN** the application starts, `/healthz` responds, one warning is logged, and requests are served with tracing off

### Requirement: API responses do not change
The status codes and bodies of `/answer`, `/seed` and every other endpoint SHALL be the same with tracing on and off.

#### Scenario: Same question, tracing on and off
- **WHEN** the same question is answered with the same retrieval results and model reply, once with tracing on and once with it off
- **THEN** both responses have the same status code, text, citations, sources and `debug.answer_mode`

### Requirement: Traces are tagged with application, environment and version
Every trace SHALL carry the application name from `DD_LLMOBS_ML_APP` (default `yt-rag`), the environment from `ENVIRONMENT`, and, when the hosting platform provides it, the deployed commit as the version.

#### Scenario: Deployed on Render
- **GIVEN** the service runs with `ENVIRONMENT=production` and the platform reports commit `aa06dec…`
- **WHEN** a question is answered
- **THEN** its trace is tagged with application `yt-rag`, environment `production` and version `aa06dec…`

### Requirement: Server log links each answer to its trace
When tracing is on, the server log line for each processed `/answer` request SHALL include that request's trace ID, so the owner can go from a log line to the trace in Datadog.

#### Scenario: Looking up a slow answer
- **WHEN** the log shows `/answer` took 9000 ms
- **THEN** the same log line includes a trace ID that finds that request's trace in Datadog

### Requirement: Pending traces are sent at shutdown
When the application shuts down gracefully, for example on a new deploy or when the free instance goes idle, it SHALL send any traces it has not yet sent before it exits.

#### Scenario: Instance stops right after a request
- **WHEN** a question is answered and the application is shut down gracefully within a second
- **THEN** that request's trace still reaches Datadog

### Requirement: Tests never contact Datadog
The automated test suite SHALL run with tracing off and send nothing to Datadog, even when the developer's local environment file contains a Datadog API key. It SHALL need no Datadog account.

#### Scenario: Developer has a key in `.env`
- **GIVEN** the developer's `.env` sets `DD_API_KEY`
- **WHEN** the test suite runs
- **THEN** no test sends data to Datadog, and tests that check tracing record spans with a test double
