# Proposal

## Why

Tracing (change `add-datadog-agent-observability`) shows what happened for each question, but not whether the answer was any good. Today the only way to tell whether a prompt, model or document change made answers better or worse is to ask questions by hand and read the replies. Datadog Agent Observability's Free plan includes evaluations and experiments at no extra cost; only LLM spans are metered. That lets us measure answer quality in two places: repeatably before a change ships, and on every live answer after it ships. Neither needs a paid service or an LLM judge.

## What Changes

- **Offline evaluation run.** Add a command, `python -m evals`, that asks a fixed set of questions about Kai through the local RAG pipeline, in process, and scores each answer with deterministic checks. The checks are: was an expected document retrieved, was it cited, does the answer mention the required facts, does it avoid forbidden content, are its citations valid, and is it plain text. The questions live in the repository in two sets:
  - **answers**: questions the profile covers, each with expected documents and facts.
  - **guardrails**: questions the profile doesn't cover, questions that aren't about Kai, requests to commit on Kai's behalf, and a greeting, each with phrases the answer must and must not contain.
- The run prints a per-question report and a pass rate, and exits non-zero if any question fails. With `DD_API_KEY` and `DD_APP_KEY` set, it also records each set as a **Datadog Experiment** against a Datadog dataset. Runs can then be compared over time by model, prompt and commit, and each question's pipeline trace (embedding, retrieval, llm) appears in Datadog. Without those keys it runs locally and sends nothing to Datadog.
- **Live answer checks.** When tracing is on, each `/answer` trace also carries rule-based evaluations computed from the answer the visitor got:
  - the highest retrieval similarity score;
  - whether the answer cites any retrieved passage;
  - whether every citation marker names a retrieved passage;
  - whether the answer is plain text, without Markdown.

  They are computed in the app with no extra model calls. They contain no visitor text, and they never change or slow the response.
- **No LLM judge.** No check calls a model. An offline run costs only its questions, about 2 Gemini requests each and about 26 for a full run. Live checks cost nothing.
- **The Datadog application key stays local.** `DD_APP_KEY`, a user-level credential, is used only by the offline run from the owner's `.env`. It is never added to the Render blueprint or needed by the deployed service.
- Docs:
  - `README.md` explains how to run an evaluation, what it costs, how to read it, and how to add a question.
  - `DEPLOYMENT.md` explains the live answer checks and where to find them in Datadog.
  - `.env.example` gains a commented, local-only `DD_APP_KEY`.
- Tests and CI stay offline. Evaluators, dataset files, the runner and live checks are tested with fakes. No test calls Gemini, Supabase or Datadog.

Out of scope: LLM-as-judge evaluations, both in this code and as Datadog's managed evaluators; running evaluations in CI, which would need Gemini and Supabase secrets; evaluating a deployed URL over HTTP; seeding the knowledge base from the runner; dashboards and monitors; and any change to `/answer`, `/seed` or other API responses.

## Capabilities

### New Capabilities
- `rag-evaluation`: measuring the quality of the assistant's answers, both offline and live.
  - Offline: the versioned question sets, the deterministic checks, the evaluation command, its report and exit status, and recording runs as Datadog Experiments.
  - Live: rule-based checks attached to traced answers.
  - Both: what the checks may send to Datadog, and the cost limits (no judge calls, local-only application key).

### Modified Capabilities
- None. The live checks build on the `observability` capability, which is still pending in the unarchived `add-datadog-agent-observability` change. Their requirements live in `rag-evaluation`, and `observability`'s requirements are unchanged.

## Impact

- Code:
  - New `app/services/answer_checks.py`: pure rule functions shared by live checks and offline evaluators.
  - `app/core/observability.py`: the span can record an evaluation, the recorder interface gains `evaluate`, and `setup` accepts an optional application key and project name for the offline runner.
  - `app/services/rag.py`: submits live checks on the `answer_question` span.
  - New `evals/` package: question sets as JSON, evaluators, runner and CLI.
- Dependencies: none new. `ddtrace` 4.17.2, already pinned, provides `submit_evaluation`, `create_dataset`, `pull_dataset` and `async_experiment`.
- Config:
  - New local-only `DD_APP_KEY`, read only by `python -m evals`.
  - No new settings on Render. `render.yaml` is unchanged.
  - `.dockerignore` excludes `evals/` from the image.
- Tests:
  - New tests for the checks, live evaluation submission, question-set validity, evaluators and the runner, all with fakes.
  - `tests/conftest.py`: `FakeRecorder` keeps evaluations, and `DD_APP_KEY` is blanked.
- External:
  - Each full offline run spends about 26 requests of the owner's Gemini free quota.
  - Each Datadog-recorded run creates experiment records, kept 90 days according to Datadog's docs, and about 13 LLM spans, far within the 40K a month.
  - A Datadog application key must be created once for experiment recording.
- Dependency on other changes: needs `add-datadog-agent-observability` merged; it is already on this branch. Archive after that change.
