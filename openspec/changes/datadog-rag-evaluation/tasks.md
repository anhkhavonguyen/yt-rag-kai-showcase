# Tasks

No task calls Gemini, Supabase or Datadog while implementing. Tests use the fakes in `tests/conftest.py` and the fake SDK pattern in `tests/test_observability.py` (the `fake_sdk` fixture). Group 7's checks need real services; they are marked **manual (owner)** and give their Gemini request cost.

## 1. Settings and shared answer rules

- [x] 1.1 Set `extra="ignore"` on `Settings` in `app/core/config.py`, and add `"DD_APP_KEY": ""` to `PLACEHOLDER_SETTINGS` in `tests/conftest.py`. Verify with new tests in `tests/test_settings_isolation.py`:
  - a temporary `.env` containing `DD_APP_KEY=real-app-key` and `SOME_UNKNOWN=1` still yields valid settings, and `Settings` has no attribute holding the app key;
  - a missing `SUPABASE_URL` still raises `ValidationError`.
- [x] 1.2 Create `app/services/answer_checks.py` with `citation_markers`, `citations_valid(answer, passage_ids)`, `plain_text(answer)` and `document_id(chunk_id)`, as in design Decision 1. Verify with `tests/test_answer_checks.py`:
  - no markers gives `citations_valid` true;
  - `[kai_salary_v1#1]` outside the passages gives false;
  - `**Azure**`, a backtick, and a line `  # Heading` each give `plain_text` false;
  - "C# and .NET" gives true;
  - `document_id("kai_dxc_v1#2") == "kai_dxc_v1"`, and an ID without `#` comes back unchanged.

## 2. Live answer checks on `/answer` traces

- [x] 2.1 In `app/core/observability.py`, add `Span.evaluate(label, value, *, assessment=None)`, a `recording` property (`True` on `Span`, `False` on `_NoopSpan`), and `evaluate(raw, label, metric_type, value, assessment)` on the `Recorder` protocol and `NoopRecorder`.
  - The metric type comes from the value: `bool` gives `boolean`, `int` or `float` gives `score`.
  - Other types are dropped with one warning through `_safely`.
  - Evaluations are sent in `_close` after `finish`, each through `_safely`.
  - In `tests/conftest.py`, give each `FakeRecorder` span dict an `evaluations` list that `evaluate` appends to.

  Verify in `tests/test_observability.py`:
  - each type mapping;
  - a string value is dropped and logged once;
  - the noop span's `evaluate` does nothing and `recording` is false;
  - an `evaluate` that raises is swallowed and the span is still finished;
  - evaluations are sent after `finish`.
- [x] 2.2 Implement `DatadogRecorder.evaluate` as `LLMObs.submit_evaluation(span=LLMObs.export_span(raw), label=..., metric_type=..., value=..., assessment=...)`, without `ml_app`. Verify with the fake SDK in `tests/test_observability.py`: the captured call has the exported span dict, label, type, value and assessment, and no `ml_app` argument.
- [x] 2.3 In `app/services/rag.py`:
  - make `_answer` return `(response, top_score)`, where `top_score` is the highest numeric `similarity` among the `vector_search` rows, or `None`;
  - in `answer_query`, while the workflow span is open and only when `span.recording`, submit the evaluations for the answer mode, as in design Decision 2.

  Verify with `tests/test_live_evaluations.py`, using the real services over fake clients as in `tests/test_observability_pipeline.py`:
  - a generated answer citing `[skills#1]`, with rows 0.82/0.77, records on the root span `retrieval_top_score` 0.82, `cites_sources` true, `citations_valid` true with pass, and `plain_text` true with pass;
  - a made-up citation gives `citations_valid` false with fail;
  - Markdown gives `plain_text` false with fail;
  - `extractive` records only `retrieval_top_score`;
  - `no_results` and `error` record none;
  - with text capture off the evaluations are still recorded and `recorder.dump()` of the evaluations contains neither the question nor the answer;
  - a recorder whose `evaluate` raises leaves the `/answer` response identical to tracing off;
  - with tracing off, `answer_checks` is never called (monkeypatched to raise).

  Also verify that `tests/test_observability_pipeline.py` passes unchanged.
- [x] 2.4 Document the live checks.
  - In `DEPLOYMENT.md` section 6, add an "Answer checks" subsection: the four labels and what each means, which answer modes carry them, where to see them in Datadog (the trace's root span, and the evaluations view filtered by label), that they cost nothing and hold no text, and how to turn them off (turn tracing off).
  - In `README.md` → Observability (optional), add one sentence that links to it.

  Verify that the subsection covers the live part of the spec requirement *Evaluation is documented*, and that the README link resolves.

## 3. Question sets

- [x] 3.1 Create the `evals/` package (`__init__.py`) and `evals/questions/answers.json` and `evals/questions/guardrails.json` with the 13 draft questions from design Decision 3, using full document IDs. Add `evals/` to `.dockerignore`. Verify by inspection that both files parse with `python -m json.tool`, and that `.dockerignore` lists `evals/`.
- [x] 3.2 Create `evals/sets.py`:
  - load and validate both files (the rules in Decision 3), raising a `QuestionSetError` that names the question ID;
  - a canonical-JSON SHA-256 `content_hash(questions)`;
  - `select(sets, set_name=None, only=None)`, answers first and file order kept, raising on an unknown ID.

  Verify with `tests/test_eval_sets.py`:
  - the real files are valid, IDs are unique across both, and every expected document is in `DOCUMENT_TITLES`;
  - the files contain the questions the spec's coverage requirement names, including `salary`, which requires "LinkedIn", and `join-call`;
  - each malformed variant (no expected documents, empty `required`, guardrail without `forbidden`, a duplicate ID across sets, an unknown field, an unknown document ID) raises an error naming its ID;
  - the hash is unchanged by key order and changes when a question is added;
  - `--only`-style selection keeps set order and rejects `nope`.

## 4. Evaluators, pass rule and report

- [x] 4.1 Create `evals/checks.py` with:
  - the evaluators from design Decision 4, for each set: `answer_mode`, `retrieval_hit`, `cites_expected_source`, `mentions_required`, `avoids_forbidden`, `citations_valid` and `plain_text`;
  - case-insensitive phrase matching with alternatives;
  - the pass rule and failure reason;
  - the summary evaluators `pass_rate` and `retrieval_hit_rate`.

  Verify with `tests/test_eval_checks.py`:
  - the spec's "Who is Kai?" scenario passes;
  - "expected document not retrieved" gives `retrieval_hit` false;
  - the return-policy answer mentioning "refund" fails `avoids_forbidden`;
  - one of two required phrases gives `mentions_required` 0.5;
  - an alternative phrase satisfies its entry;
  - `extractive` fails with reason "model unavailable (extractive)", and `error`/`no_results` with "search unavailable";
  - the summary evaluators compute rates from an `evaluators_results` dict;
  - over every real question with a sample output, each evaluator returns the same non-`None` type.
- [x] 4.2 Add the report formatter to `evals/checks.py` (or `evals/report.py`). It prints:
  - one line per question: PASS or FAIL, ID, and the failed checks, or the unavailability reason;
  - per-set and total counts;
  - an experiment-links line only when links are given.

  Verify with tests: 12 of 13 passing prints the failing ID with its failed checks and `total 12/13`; there is no links line in local mode.

## 5. Runner and command line (local mode)

- [x] 5.1 Create `evals/runner.py`:
  - a `Pacer(delay, clock, sleep)`;
  - the async task, which calls `rag_service.answer_query(question, top_k=ANSWER_TOP_K)` with `ANSWER_TOP_K` read from `AnswerRequest`'s `top_k` default, and returns `{answer, answer_mode, citations, passage_ids, latency_ms}`;
  - the local backend, producing `QuestionResult`s.

  Verify with `tests/test_eval_runner.py` over the `rag` fixture's fakes:
  - each selected question is answered once, in order (from `fake_chat.calls`);
  - with an injected clock, starts are at least `delay` apart, and a delay of 0 never sleeps;
  - `FakeDatabase.writes` is empty after a run;
  - the output fields come from the response.
- [x] 5.2 Create `evals/config.py` (`EvalSettings` with `dd_app_key`, `.env`, `extra="ignore"`) and `evals/__main__.py`:
  - argparse with `--set`, `--only`, `--local` and `--delay` (default 5);
  - lazy import of `app` inside `main()`, turning a `ValidationError` into a list of field names only;
  - `db.connect()`/`db.disconnect()` around the run;
  - the "results stay local (<reason>)" line;
  - exit codes 0, 2 and 1, as in design Decision 8.

  Add `connect`/`disconnect` to `FakeDatabase`. Verify with tests:
  - all passing exits 0, and one failure exits 2;
  - an unknown `--only` ID or an invalid question set exits 1 with no question asked;
  - a simulated `ValidationError` for missing `SUPABASE_URL`, with input values containing `secret-value-xyz`, exits 1, names the field, and the output doesn't contain `secret-value-xyz`;
  - `DD_API_KEY` set without `DD_APP_KEY` prints "results stay local (no DD_APP_KEY)", and the Datadog SDK guard isn't triggered;
  - `--local` with both keys stays local;
  - a failing `db.connect` exits 1.

## 6. Recording runs as Datadog experiments

- [x] 6.1 Extend `observability.setup(settings, *, app_key=None, project_name=None)` to pass both to `LLMObs.enable` only when given. Verify in `tests/test_observability.py` with `fake_sdk`:
  - the captured `enable` arguments have neither key when not given, and both when given;
  - the app key value never appears in `caplog`;
  - the existing lifespan test still shows the web app calling `setup(settings)` without them.
- [x] 6.2 Add the commit helper, `git rev-parse --short HEAD` plus `-dirty` when `git status --porcelain` isn't empty, or `unknown` when git fails. Verify with a monkeypatched `subprocess.run`: clean, dirty, and git missing.
- [x] 6.3 Implement the Datadog backend in `evals/runner.py`.
  - **Prepare first:** `setup` with the app key and the project name `DD_LLMOBS_ML_APP`, then for each needed set dataset `yt-rag-<set>-<hash8>`, `pull_dataset`, or `create_dataset` with records `{input_data, expected_output, metadata}` on "not found".
  - **Run:** `async_experiment(name=<set>, task, dataset, evaluators, summary_evaluators, project_name, config, tags)` and `run(jobs=1)`.
  - **Results:** rows mapped back to `QuestionResult` by `idx`, with a row `error` reported as "task error: <type>", and experiment URLs printed.

  Verify with a fake `LLMObs` in `tests/test_eval_runner.py`, whose `async_experiment().run()` calls the task for each record in order and applies the evaluators:
  - two runs without edits use the same dataset name, and `create_dataset` is called once;
  - adding a question changes the name;
  - `run` is called with `jobs=1`;
  - `config` has `chat_model`, `embed_model`, `top_k`, `temperature` and `commit`;
  - a `pull_dataset` that raises `PermissionError` exits 1, `fake_chat.calls` is empty, and neither `DD_API_KEY` nor `DD_APP_KEY` appears in the captured output;
  - the report prints each experiment URL;
  - local and Datadog backends give the same report for the same fake answers.
- [x] 6.4 Document the offline run.
  - In `README.md`, add an "Evaluating answers" section covering:
    - prerequisites: `.env` with the Gemini and Supabase keys, and the default documents seeded;
    - the commands and options;
    - the cost: about 2 Gemini requests per question, about 26 for a full run, about 10 for `--set guardrails`;
    - how to read the report, and the exit codes;
    - recording to Datadog: create an application key under Organization Settings → Application Keys, put `DD_APP_KEY` only in the local `.env` and never on Render, and revoke it when done;
    - where to find the experiments, and filtering visitor traces by `env:production`;
    - that experiment records hold the test questions and answers;
    - how to add a question: edit the JSON, run the tests, and expect a new dataset.
  - In `.env.example`, add a commented `# DD_APP_KEY=` line marked local-only.

  Verify:
  - the section covers the spec requirement *Evaluation is documented*;
  - `git grep -n DD_APP_KEY render.yaml` finds nothing;
  - `git grep -nE "DD_APP_KEY=.+[A-Za-z0-9]{20}"` finds no key in the repository;
  - the README's links resolve.

## 7. Integration checks

- [ ] 7.1 Run `ruff check .`, `pytest` and `docker build -t yt-rag:ci .` locally. Verify all three pass with no network access to Gemini, Supabase or Datadog, and that `docker run --rm --entrypoint ls yt-rag:ci /app/evals` fails because the directory isn't in the image.
- [ ] 7.2 **Manual (owner, local, about 10 Gemini requests).** With the Gemini and Supabase keys in `.env` and the defaults seeded, run `python -m evals --set guardrails --local`. Verify the report lists the 5 guardrail questions and the exit status matches it. Fix any false failure by editing phrases and rerunning that question with `--only <id>`, about 2 requests each.
- [ ] 7.3 **Manual (owner, local, about 36 Gemini requests).** With `DD_API_KEY`, `DD_SITE` and `DD_APP_KEY` in `.env`, run `python -m evals`, then `python -m evals --set guardrails`. Verify:
  - Datadog shows experiments `answers` and `guardrails` in project `yt-rag`, with the run config and the summary `pass_rate`;
  - each record shows embedding → retrieval → llm spans nested under it, which settles design Decision 5;
  - the second guardrails run reuses the same dataset;
  - the printed links open the experiments;
  - the output and log show no `localhost:8126`/Agent errors and neither key.
- [ ] 7.4 **Manual (owner, deployed instance, about 2 Gemini requests).** After deploying with tracing on, ask one question on the live page. Verify that the trace's root span shows `retrieval_top_score`, `cites_sources`, `citations_valid` and `plain_text`, with no question or answer text in them. Decide the design's open question on `eval_scope` from what Datadog shows.

## Workflow follow-up

- Archive after `add-datadog-agent-observability` is archived. The live checks build on its `observability` capability.
