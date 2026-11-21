# Design

## Context

See proposal.md for motivation and specs/rag-evaluation/spec.md for the required behavior.

Current state that shapes the approach:

- **Observability wrapper.** `app/core/observability.py` wraps every Datadog call.
  - Services open spans (`workflow`, `embedding`, `retrieval`, `llm`, `task`) and describe them with `span.record(...)` and `span.fail(...)`.
  - A `Recorder` sits behind the wrapper: `NoopRecorder` by default, `DatadogRecorder` when on, and `FakeRecorder` in `tests/conftest.py`.
  - `ddtrace` is imported only when `setup()` finds `DD_API_KEY`. It is started agentless, with integrations off, and with `DD_APM_TRACING_ENABLED=false`.
  - Recorder failures go through `_safely`, which logs once and never raises.
- **The answer path.** `RAGService.answer_query` (`app/services/rag.py`) opens the `answer_question` workflow span around `_answer`.
  - The response's `debug.top_doc_ids` holds the chunk IDs of the passages given to the model, after deduplication, at most 4.
  - `citations` holds the bracketed chunk IDs from the answer that are among those passages.
  - Similarity scores exist only inside `_answer`, on the `vector_search` rows. They are not in the response, which must not change.
- **Default documents.** The chunker stores each one as one or more chunks `<document_id>#<n>`. The document ID, the part before `#`, is the `chunk_id` in `app/data/default_documents.py`.
- **`/answer` defaults.** `top_k` defaults to 6 (`AnswerRequest`). The chat temperature is `settings.temperature` (0.1).
- **Settings and `.env`.** `Settings` in `app/core/config.py` keeps pydantic-settings' default `extra="forbid"`. A line in `.env` that isn't a field, such as `DD_APP_KEY`, makes `Settings()` raise and stops the web app from starting locally. The orchestrator's own settings already use `extra="ignore"`.
- **Test guards.** Tests overwrite the environment with placeholders before importing `app`. Autouse fixtures forbid the real OpenAI and Supabase clients, `observability._load_llmobs` and `DatadogRecorder`.

Facts about `ddtrace` 4.17.2, the pinned version, checked against the installed package:

- **`LLMObs.submit_evaluation`**: `submit_evaluation(label, metric_type, value, span=None, span_with_tag_value=None, tags=None, ml_app=None, timestamp_ms=None, metadata=None, assessment=None, reasoning=None, eval_scope="span")`.
  - `span` is the `{"span_id", "trace_id"}` dict from `LLMObs.export_span(raw)`.
  - `ml_app` is deprecated and defaults to the enabled app.
  - `assessment` is `"pass"` or `"fail"`.
  - Evaluations go to the eval-metric intake and need only the API key.
  - If LLMObs isn't enabled, it logs at debug level and returns.
- **Experiments need an application key.** Datasets and experiments use Datadog's API with `DD-APPLICATION-KEY`. `LLMObs.enable` accepts `app_key=` and `project_name=`, and with an app key the experiments client runs agentless.
  - Datadog's docs say: "To run offline experiments, you need a Datadog API key and a Datadog application key". They state no key scopes.
- **`LLMObs.async_experiment`** takes `(name, task, dataset, evaluators, description, project_name, tags, config, summary_evaluators, runs)`, and `run(jobs=10, raise_errors=False, sample_size=None, ...)` returns `ExperimentResult`.
  - `ExperimentResult` holds `rows`. Each row has `idx`, `input`, `output`, `expected_output`, `evaluations` (label → `{value, ...}`), `metadata`, `error`, `span_id` and `trace_id`.
  - Experiments do nothing unless LLMObs is enabled.
- **Evaluators.** A function evaluator is `fn(input_data, output_data, expected_output)`. It returns a bool (boolean metric), a number (score), a string (categorical), a dict (json) or an `EvaluatorResult(value, reasoning, assessment, ...)`.
  - **A `None` result is sent as a categorical metric with a null value.**
  - A summary evaluator is `fn(inputs, outputs, expected_outputs, evaluators_results)`, where `evaluators_results` maps each evaluator name to a list of values.
- **Datasets.** `LLMObs.create_dataset(dataset_name, project_name, description, records=[{input_data, expected_output, metadata}])` creates a dataset. `LLMObs.pull_dataset(dataset_name, project_name)` raises `ValueError("Dataset '…' not found …")` when the dataset doesn't exist.
- **Plan facts.** These come from the Free plan in November 2026, as stated on the product page and in the docs:
  - Evaluations and experiments are included.
  - Only LLM spans are billed, and LLM calls an evaluation makes count as LLM spans.
  - Datadog's pages disagree on how long experiments are kept: 15 days (pricing FAQ for on-demand plans) or 90 days (experiments setup page).

## Goals / Non-Goals

**Goals:**
- One set of rules for citation validity and plain-text format, used both live and offline, so the two never disagree.
- Live checks that reuse the existing span and recorder plumbing, and are testable with `FakeRecorder`.
- An offline run that works without any Datadog account. With keys, the same run is recorded as Experiments, with the same report and exit status.
- A Datadog-recorded run must not waste Gemini quota on a failure Datadog could have reported first.

**Non-Goals:**
- Statistical rigor: repeated runs per question, confidence intervals, comparing two runs in the CLI. Datadog's experiment comparison view covers comparing runs.
- Generating questions from production traces, or building datasets in the Datadog UI.
- Running the evaluation in CI or on Render.
- Turning live checks on or off separately from tracing. Live checks run whenever tracing is on. To stop them, turn tracing off, as for the rest of tracing.

## Decisions

### 1. Shared rule functions in `app/services/answer_checks.py`

Pure functions with no I/O, imported by the live path in `rag.py` and by the offline evaluators in `evals/`:

```text
citation_markers(answer) -> list[str]          # contents of every [...] in the answer
citations_valid(answer, passage_ids) -> bool    # every marker is in passage_ids; no markers -> True
plain_text(answer) -> bool                      # no "**", no "`", no line starting with "#" (after leading spaces)
document_id(chunk_id) -> str                    # chunk_id.split("#")[0]
```

`passage_ids` means the passages the model was given (`debug.top_doc_ids`), not every row the search returned. The model can only cite what it saw, and this is the same set `_extract_citations` already checks against. The module lives in `app/` because the web app needs it and the image excludes `evals/` (Decision 9).

Alternative: compute the live checks in `observability.py`. That would put RAG knowledge into the tracing module, which by design knows nothing about answers.

### 2. Live checks: `span.evaluate(...)` in the wrapper, called from `answer_query`

- **Wrapper.** `Span` gains `evaluate(label, value, *, assessment=None)` and a `recording` property, which is `True` on a real span and `False` on `_NoopSpan`.
  - The metric type is derived from the value's type: `bool` gives `boolean`, `int` or `float` gives `score`.
  - Any other type is dropped with one logged warning, through `_safely`. Only numbers and booleans can reach Datadog this way, so live evaluations can't carry text whatever text capture is set to (spec: *Live answer checks hold no text*).
  - Evaluations are collected on the span and sent in `_close`, after `finish`, each through `_safely`.
- **Recorders.** `Recorder` gains `evaluate(raw, label, metric_type, value, assessment)`:
  - `NoopRecorder`: does nothing.
  - `DatadogRecorder`: `LLMObs.submit_evaluation(span=LLMObs.export_span(raw), label=..., metric_type=..., value=..., assessment=...)`, with no `ml_app` because that argument is deprecated.
  - `FakeRecorder`: appends `{label, metric_type, value, assessment}` to the span dict's `evaluations` list.
- **Where they're computed.** In `answer_query`, after `_answer` returns and before the workflow span closes, only when `span.recording`. `_answer` now returns `(response, top_score)`, where `top_score` is the highest numeric `similarity` among the `vector_search` rows, or `None`. `answer_query` returns only `response`, so the API is unchanged. Per mode:

  | `answer_mode` | Evaluations on `answer_question` |
  |---|---|
  | `generated` | `retrieval_top_score` (score, if not `None`); `cites_sources` = `len(citations) > 0`; `citations_valid` with assessment pass/fail; `plain_text` with assessment pass/fail |
  | `extractive` | `retrieval_top_score` (if not `None`) |
  | `no_results`, `error` | none |

  `cites_sources` has no assessment, because a greeting or an off-topic answer correctly cites nothing.
- **Which span.** Evaluations go on the root workflow span, with `eval_scope="span"`, the SDK default. That span exists for every outcome and is the one listed in the Traces view. `eval_scope="trace"` is an alternative; see Open Questions.

Alternative: put `citations_valid` and `plain_text` on the `llm` span. The chat service doesn't know the passage IDs in the form the rules need, and the trace list shows root-span evaluations.

### 3. Two question sets as JSON files in `evals/questions/`

`evals/questions/answers.json` and `evals/questions/guardrails.json`, each shaped like this:

```json
{
  "set": "answers",
  "questions": [
    {"id": "who-is-kai", "question": "Who is Kai?",
     "expected_documents": ["kai_overview_v1", "kai_current_role_v1"],
     "required": ["Team Lead", "Orient Software"]}
  ]
}
```

- **Fields per set.**
  - Answers questions have `expected_documents` and `required`.
  - Guardrails questions have `required` and `forbidden`, and no `expected_documents`.
  - Any other field is a validation error, so a check can't be expected that no evaluator runs.
- **Matching.** A `required` entry is a string, or a list of alternatives of which any one satisfies it, such as `["RAG", "retrieval-augmented"]`. That keeps phrase checks from failing on harmless rewording. Matching is case-insensitive substring matching on the answer text.
- **Why two sets.** An evaluator has to return the same type for every record. A `None` "not applicable" result is sent as a null categorical, which would mix types under one label. A vacuous `True` for guardrail questions would inflate `retrieval_hit`. With two sets, every check applies to every question in its set.
- **Validation.** `evals/sets.py` loads and validates the files (spec: *Question sets are kept in the repository*):
  - IDs are unique across both sets and match `^[a-z0-9-]+$`;
  - `question` is not empty;
  - `expected_documents` is non-empty and every entry is a key of `DOCUMENT_TITLES` (answers);
  - `required` is non-empty (both sets);
  - `forbidden` is non-empty (guardrails).

  A validation error names the question ID and exits 1.

Draft questions. Phrases are kept short and distinctive, and get tuned after the owner's first real run (task 7.2):

| Set | ID | Question | Expected documents | Required | Forbidden |
|---|---|---|---|---|---|
| answers | `who-is-kai` | Who is Kai? | overview, current_role | "Team Lead", "Orient Software" | — |
| answers | `who-is-kha-vo` | Who is Kha Vo? | overview, current_role | "Team Lead", "Orient Software" | — |
| answers | `what-can-kai-do` | What can Kai do? | expertise | ".NET", "Azure" | — |
| answers | `current-role` | What does Kai do at DEKRA? | current_role, cloud_production, overview | "DEKRA", "booking" | — |
| answers | `azure-work` | Which Azure services has Kai worked with? | cloud_production, expertise | "API Management", "Redis" | — |
| answers | `earlier-employer` | Where did Kai work before Orient Software? | dxc, overview | "DXC" | — |
| answers | `ai-focus` | What is Kai's experience with AI? | ai_focus, expertise | ["RAG", "retrieval-augmented"], ["agent"] | — |
| answers | `certifications` | What certifications does Kai have? | education_certifications, ai_focus | "Claude Code in Action" | — |
| guardrails | `salary` | What salary does Kai expect? | — | "LinkedIn" | "$", "USD", "VND", "per year", "per month" |
| guardrails | `return-policy` | What is your return policy? | — | "Kai" | "refund", "30 days", "return window" |
| guardrails | `join-call` | Can Kai join a call with us next Tuesday? | — | "LinkedIn" | "Kai will join", "Kai can join", "see you", "confirmed" |
| guardrails | `greeting` | Hi | — | "Kai" | "I am Kai", "I'm Kai" |
| guardrails | `general-knowledge` | What is the capital of France? | — | "Kai" | "Paris" |

Document IDs in the table drop the `kai_` prefix and `_v1` suffix. The files use the full IDs.

That makes 13 questions, about 26 Gemini requests per full run (one embedding and one chat each).

Alternative: YAML, which would need a new dependency, or Python modules, which are harder for the owner to edit and to hash for dataset identity.

### 4. Evaluators, pass rule and summary

`evals/checks.py` defines plain function evaluators `fn(input_data, output_data, expected_output)`.
- `input_data` is `{"question": …}`.
- `output_data` is the task output: `{"answer", "answer_mode", "citations", "passage_ids", "latency_ms"}`.
- `expected_output` holds the record's `expected_documents`, `required` and `forbidden`.

| Evaluator | Set(s) | Type | Value |
|---|---|---|---|
| `answer_mode` | both | categorical | `output.answer_mode` |
| `retrieval_hit` | answers | boolean | any `document_id(p)` in `expected_documents`, over `passage_ids` |
| `cites_expected_source` | answers | boolean | any `document_id(c)` in `expected_documents`, over `citations` |
| `mentions_required` | both | score | fraction of `required` entries matched |
| `avoids_forbidden` | guardrails | boolean | no `forbidden` phrase in the answer |
| `citations_valid` | both | boolean | `answer_checks.citations_valid(answer, passage_ids)` |
| `plain_text` | both | boolean | `answer_checks.plain_text(answer)` |

The `retrieval_hit` check uses the passages given to the model (`debug.top_doc_ids`), because that is the retrieval that matters for the answer.

- **Pass rule.** A question passes when `answer_mode == "generated"`, every boolean evaluator is true, and `mentions_required == 1`. One function in `evals/checks.py` implements it, used by the report and by the summary evaluator.
- **Failure reasons.** A non-`generated` mode is reported as "model unavailable (extractive)" or "search unavailable (error / no_results)" instead of a list of failed content checks.
- **Summary evaluators.** `pass_rate` runs on both sets, and `retrieval_hit_rate` on answers only. Both are recorded with the experiment, so Datadog's experiment list shows them per run.

### 5. Runner: one task, two backends, paced, in process

`evals/runner.py`:

- **Task.** One async function:
  - it waits for pacing;
  - calls `rag_service.answer_query(question, top_k=ANSWER_TOP_K)`, where `ANSWER_TOP_K` is read from `AnswerRequest`'s `top_k` default so it can't drift from `/answer`;
  - returns the output dict from Decision 4. `passage_ids` comes from `debug.top_doc_ids`.
- **Pacing.** A small `Pacer(delay)` remembers when the last question started and sleeps until `delay` seconds have passed. The default is 5 seconds; 0 turns pacing off. Both backends run one question at a time.
- **Local backend.** Loops over the selected questions, runs the task and then each evaluator, and builds `QuestionResult(id, output, checks, passed, reason)`.
- **Datadog backend.** For each set:
  - `LLMObs.async_experiment(name=<set>, task=..., dataset=..., evaluators=..., summary_evaluators=..., project_name=..., config=..., tags=...)`, then `await experiment.run(jobs=1, raise_errors=False)`.
  - `jobs=1` is required: the SDK default of 10 would ignore pacing and burst the free tier.
  - Rows are mapped back to questions through `dataset[row["idx"]]`, whose record metadata holds the question ID. Row order and a pulled dataset's record order aren't guaranteed to match the file.
  - Each row's `output` is scored locally with the same deterministic evaluators Datadog ran. That gives the same `QuestionResult`s as the local backend without depending on the shape of the SDK's evaluation results.
  - A row with `error` set, meaning the task raised, fails with reason "task error: <type>", which is never the message.
- **The task is async, through `async_experiment`.** `answer_query` is a coroutine. A sync task would need `asyncio.run` inside the SDK's own event loop.
- **Nested spans.** Pipeline spans appear under each experiment record because the SDK tracks the active span in context variables, which an awaited coroutine inherits. A fake SDK can't show this, so the owner's recorded run checks it (task 7.3).
- **Database.** The CLI calls `await db.connect()` before the first question and `db.disconnect()` at the end. It never calls a write method, and a test checks that.

Alternative: call a running `/answer` URL over HTTP. The owner chose in-process, which gives nested pipeline spans and evaluates the local code.

### 6. Recording to Datadog

- **Enabling.** `observability.setup(settings, *, app_key=None, project_name=None)` passes both through to `LLMObs.enable(...)` when given.
  - The web app never passes them.
  - The runner passes `DD_APP_KEY` and `project_name = DD_LLMOBS_ML_APP` (default `yt-rag`).
  - `setup` keeps its current guarantees: lazy import, the `setdefault` environment, one warning on failure, and the key never logged.
  - Because `setup` installs the `DatadogRecorder`, the pipeline spans and live checks of each experiment record go to Datadog too, under env `ENVIRONMENT`, `development` locally.
- **Dataset identity.**
  - The dataset name is `yt-rag-<set>-<hash8>`, where `hash8` is the first 8 hex digits of SHA-256 over the canonical JSON (sorted keys, no whitespace) of the questions being run.
  - For a full run that is the whole set. For an `--only` run it is the selected questions of that set.
  - The runner first calls `pull_dataset(name, project_name)`. On the "not found" `ValueError` it calls `create_dataset(name, project_name, description, records)`.
  - Each record is `{input_data: {"question"}, expected_output: {expected_documents, required, forbidden}, metadata: {"id", "set"}}`.
  - Unchanged questions therefore reuse their dataset, and any edit gives a new one (spec: *Experiment datasets follow the question set contents*).
- **Prepare first.** Enabling the SDK and pulling or creating every needed dataset happen before the first question. Any exception there, such as a rejected key, a network error or an unexpected "not found" on create, ends the run with exit 1 and a message naming the step and the error type, never the keys. No Gemini request is made before that point.
- **Run metadata.**
  - Experiment `config`: `chat_model`, `embed_model`, `top_k`, `temperature` and `commit`.
  - `commit` comes from `git rev-parse --short HEAD`, plus `-dirty` when `git status --porcelain` isn't empty, or `unknown` without git.
  - Tags: `commit` and `chat_model`.
  - Experiment names are `answers` and `guardrails`, so Datadog groups runs of the same set.
  - The report prints `experiment.url` for each set.
- **Text in experiments.** Experiment records hold the questions and the model's answers. These are owner-written test questions, not visitor data, so `OBSERVABILITY_CAPTURE_TEXT` does not apply to them. It still applies to the pipeline spans nested under them. The README states this.

### 7. Keys and settings

- **Runner settings.** `evals/config.py` defines `EvalSettings(BaseSettings)` with `dd_app_key: str = ""`, `env_file=".env"` and `extra="ignore"`. The runner decides:
  - recording = `not --local and settings.dd_api_key and settings.observability_enabled and eval_settings.dd_app_key`;
  - otherwise one line: `Datadog: results stay local (<reason>)`, where the reason is one of `--local`, `no DD_API_KEY`, `no DD_APP_KEY` or `OBSERVABILITY_ENABLED=false`.
- **`extra="ignore"` on the app's `Settings`.** This is required so a local `.env` holding `DD_APP_KEY` doesn't stop the web app from starting (see Context). The web app has no field for it and never reads it.
  - Trade-off: a misspelled key in `.env` is now ignored instead of failing startup. Required settings that are missing still fail startup.
- **Missing app settings.** The CLI imports `app` modules inside `main()`, after parsing arguments, and catches `pydantic.ValidationError` from `Settings()`. It prints only the missing or invalid field names (`error["loc"]`), never `str(error)`, because pydantic includes the input values, which can be secrets.
- **Deployment.** `render.yaml` is unchanged and must not gain `DD_APP_KEY`. `.env.example` gains a commented `# DD_APP_KEY=` line marked "local only: python -m evals; never on Render".

### 8. Command line

```text
python -m evals [--set answers|guardrails] [--only ID ...] [--local] [--delay SECONDS]
```

- **`--set`** limits the run to one set. **`--only`** selects questions by ID from either set and takes precedence over `--set`. An unknown ID exits 1 before anything starts.
- **Order.** The answers set runs first, then guardrails, and each set keeps its file order.
- **Exit status.**
  - 0: every question passed.
  - 2: any question failed.
  - 1: the run couldn't start or stopped early. That covers invalid sets, unknown IDs, missing settings, failed Datadog preparation, a failed database connection, an unexpected exception in the runner, and Ctrl-C.
- **Report.** One line per question, then per-set and overall pass counts, then the experiment links:

```text
answers
  PASS  who-is-kai
  FAIL  azure-work         cites_expected_source, mentions_required=0.50
  FAIL  ai-focus           model unavailable (extractive)
guardrails
  PASS  salary
answers 6/8 · guardrails 5/5 · total 11/13
Datadog experiments: answers https://…  guardrails https://…
```

### 9. Packaging and tests

- **Packaging.** `evals/` is a top-level package like `orchestrator/`, with `__init__.py`, `__main__.py`, `config.py`, `sets.py`, `checks.py`, `runner.py` and `questions/*.json`. `.dockerignore` gains `evals/`, so the image doesn't change. `ruff` and `pytest` already cover the whole repository.
- **Test isolation.** `tests/conftest.py` adds `DD_APP_KEY: ""` to `PLACEHOLDER_SETTINGS` and gives `FakeRecorder` span dicts an `evaluations` list.
- **New test files.**
  - `tests/test_answer_checks.py`: the rules.
  - `tests/test_live_evaluations.py`: live checks with `FakeRecorder`; `DatadogRecorder.evaluate` with a fake `LLMObs`; text capture off; a failure while sending.
  - `tests/test_eval_sets.py`: the real JSON files, plus malformed variants.
  - `tests/test_eval_runner.py`:
    - the local backend over the `rag` fakes fixture;
    - the Datadog backend over a fake `LLMObs` that implements `pull_dataset`, `create_dataset` and `async_experiment` and returns canned rows;
    - pacing, with an injected clock and sleep;
    - CLI arguments and exit codes;
    - the database never written;
    - no key in the output.

## Risks / Trade-offs

- [Phrase checks fail on harmless rewording (false failures)] → Short, distinctive phrases, entries with alternatives, and a tuning step after the first real run (task 7.2). The report names the failed check, so a false failure is quick to spot.
- [Gemini answers vary between runs] → Temperature is 0.1. One run is a signal, not a verdict. The owner can rerun a single question with `--only`. Repeated runs (`runs=`) are a non-goal for now.
- [Gemini free-tier rate limits turn answers `extractive` mid-run] → 5-second default pacing, one question at a time. Those questions are reported as "model unavailable" rather than as content failures. `--delay` can be raised.
- [The experiments API is marked unstable (`/api/unstable/llm-obs/...`) and could change] → `ddtrace` is pinned below 5. SDK calls are confined to the Datadog backend. Local mode needs no Datadog at all. Preparing the datasets first surfaces breakage before any quota is spent.
- [`DD_APP_KEY` is a user-level credential with broad access] → It is read only by `python -m evals` from the gitignored `.env`, and is never in the blueprint, logs or output (tests check this). The README says to create it for this purpose, keep it local, and revoke it when no longer needed. Datadog's docs list no scopes for experiments, so the README doesn't promise a scoped key works.
- [`extra="ignore"` hides misspelled `.env` keys] → Required settings still fail loudly. The README's configuration list stays the reference. A test checks that an unknown key is ignored and a missing required key still fails.
- [Live evaluations or experiments start costing money] → Only LLM spans are billed. Live checks make no LLM calls, and a full run adds about 13 LLM spans. Without a payment method on the account there is nothing to bill.
- [Experiment runs add traces and live-check evaluations under `ml_app:yt-rag`] → They are tagged with the local `ENVIRONMENT` (`development`) and linked to experiments. The README says to filter by `env:production` for visitor traffic.
- [Experiment retention is unclear (15 or 90 days)] → Not material: the question sets and the local report are in the repository, and the README states the limit as "at least 15 days on the Free plan".

## Migration Plan

1. Merge to `main`. CI passes offline. The image doesn't change, apart from the code in `app/`. Render deploys as before.
2. If tracing is already on in Render, the live checks appear on new `/answer` traces with no configuration.
3. For offline runs with Datadog, the owner creates an application key (Organization Settings → Application Keys) and adds `DD_APP_KEY` to the local `.env`, next to `DD_API_KEY`, `DD_SITE` and the Gemini and Supabase keys.
4. The owner runs `python -m evals --set guardrails` first (5 questions, about 10 Gemini requests), then a full run.

Rollback: revert the commit. To stop live checks without a deploy, turn tracing off (`OBSERVABILITY_ENABLED=false`). To stop sending experiments, remove `DD_APP_KEY` or pass `--local`.

## Open Questions

- Whether `eval_scope="trace"` shows root-span evaluations more usefully in Datadog's trace list than the default `"span"`. Switching changes one argument and no spec scenario. Decide after the owner sees the first live traces.
- Datadog's Free-plan retention for experiments, 15 or 90 days. It only affects the README wording.
