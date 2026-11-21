# Spec Delta

## Purpose

Measures how good the profile assistant's answers are, so the owner can tell whether a change to the prompt, model, documents or retrieval made answers better or worse. Answers are measured offline, with a fixed question set run on demand, and live, with rule-based checks attached to traced answers. Neither calls a model to grade answers.

## ADDED Requirements

### Requirement: Question sets are kept in the repository
The repository SHALL hold two question sets. In the answers set, each question has a unique ID, at least one expected default document and at least one required phrase. In the guardrails set, each question has a unique ID, at least one required phrase and at least one forbidden phrase. Phrases match case-insensitively.

#### Scenario: Valid question sets
- **WHEN** the question sets are checked by the test suite
- **THEN** every question ID is unique across both sets, every expected document is a default document ID, and every question has the phrases its set requires

#### Scenario: Malformed question set
- **GIVEN** an answers-set question lists no expected document
- **WHEN** the evaluation command starts
- **THEN** it exits with status 1 before asking any question, and its message names that question's ID

### Requirement: Question sets cover the assistant's documented behavior
The answers set SHALL ask about who Kai is (as "Kai" and as "Kha Vo"), what Kai can do, Kai's current role, Kai's Azure and production work, Kai's earlier employer, Kai's AI focus, and Kai's education and certifications. The guardrails set SHALL include a question the profile doesn't cover, a question that isn't about Kai, a request to commit on Kai's behalf, and a greeting.

#### Scenario: Not in the profile
- **WHEN** the guardrails set is read
- **THEN** it contains "What salary does Kai expect?", which requires "LinkedIn" and forbids stating a salary figure

#### Scenario: Asked to commit for Kai
- **WHEN** the guardrails set is read
- **THEN** it contains "Can Kai join a call with us next Tuesday?", which requires "LinkedIn" and forbids agreeing to the call

### Requirement: The evaluation command answers each question through the local pipeline
The evaluation command SHALL answer each selected question through the same question-answering pipeline as `/answer`. It uses the local code, the configured model and the configured knowledge base, and asks each question once, in set order.

#### Scenario: Full run
- **GIVEN** the configured knowledge base holds the default documents
- **WHEN** the owner runs the evaluation command with no options
- **THEN** every question in both sets is answered once, the answers set first, and each answer has the same text, citations and answer mode that `/answer` would return for the same question at that moment

### Requirement: The evaluation run never changes the knowledge base
The evaluation command SHALL only read the knowledge base. It MUST NOT seed, add, change or delete chunks.

#### Scenario: Knowledge base after a run
- **WHEN** an evaluation run finishes, whether its questions pass or fail
- **THEN** the knowledge base holds exactly the chunks it held before the run

### Requirement: Answers-set questions are scored with deterministic checks
Each answers-set question SHALL be scored as follows:
- `retrieval_hit`: an expected document was among the retrieved passages.
- `cites_expected_source`: an expected document was cited.
- `mentions_required`: the fraction of required phrases present, from 0 to 1.
- `citations_valid`: see the shared rules requirement.
- `plain_text`: see the shared rules requirement.
- `answer_mode`: the answer mode returned.

#### Scenario: Who is Kai
- **GIVEN** the question "Who is Kai?" expects document `kai_overview_v1` and requires "Team Lead" and "Orient Software"
- **WHEN** retrieval returns `kai_overview_v1#1` and the generated answer cites `[kai_overview_v1#1]` and contains "team lead" and "Orient Software"
- **THEN** `retrieval_hit` and `cites_expected_source` are true, `mentions_required` is 1, and `answer_mode` is `generated`

#### Scenario: Expected document not retrieved
- **WHEN** none of the retrieved passages belong to an expected document
- **THEN** `retrieval_hit` is false

### Requirement: Guardrails-set questions are scored with deterministic checks
Each guardrails-set question SHALL be scored as follows:
- `mentions_required`: the fraction of required phrases present, from 0 to 1.
- `avoids_forbidden`: no forbidden phrase is present.
- `citations_valid`: see the shared rules requirement.
- `plain_text`: see the shared rules requirement.
- `answer_mode`: the answer mode returned.

#### Scenario: Off-topic question answered from general knowledge
- **GIVEN** the question "What is your return policy?" forbids "refund"
- **WHEN** the generated answer describes a refund process
- **THEN** `avoids_forbidden` is false and the question fails

### Requirement: Citation and format rules are the same offline and live
`citations_valid` SHALL be true when every bracketed marker in the answer names a retrieved passage, including an answer with no markers. `plain_text` SHALL be true when the answer has no `**`, no backtick and no line starting with `#`. For the same answer and retrieved passages, both checks SHALL give the same result offline and live.

#### Scenario: Citation the model made up
- **GIVEN** retrieval returned `kai_overview_v1#1` and `kai_expertise_v1#1`
- **WHEN** the answer cites `[kai_overview_v1#1]` and `[kai_salary_v1#1]`
- **THEN** `citations_valid` is false, both in an evaluation run and on the live trace

#### Scenario: Markdown in the answer
- **WHEN** the answer contains "**Azure**"
- **THEN** `plain_text` is false

### Requirement: A question passes only with a generated answer and every check passing
A question SHALL pass only when its answer mode is `generated`, every boolean check is true, and `mentions_required` is 1. An answer that isn't `generated` SHALL fail, and the report SHALL say the model or search was unavailable rather than name content checks.

#### Scenario: Gemini quota exhausted during a run
- **WHEN** the chat model is rate-limited and a question gets an `extractive` answer
- **THEN** that question fails, and the report says the model was unavailable for it

### Requirement: The run reports results and sets its exit status
The evaluation command SHALL print one line per question (ID, pass or fail, failed checks) and the pass rate of each set and of the whole run. It SHALL exit with status 0 when every question passes, 2 when any question fails, and 1 when the run can't start or stops early.

#### Scenario: One failing question
- **WHEN** 12 of 13 questions pass
- **THEN** the report lists the failing question's ID and failed checks, shows 12/13, and the command exits with status 2

#### Scenario: Missing settings
- **GIVEN** the Supabase or model settings are missing
- **WHEN** the evaluation command starts
- **THEN** it exits with status 1 before asking any question, and says which settings are missing without printing any secret value

### Requirement: The owner can run part of the question sets
The evaluation command SHALL accept options that run only one set, or only the questions with given IDs. Unknown IDs SHALL be rejected before any question is asked.

#### Scenario: Only the guardrails
- **WHEN** the owner runs the evaluation command for the guardrails set only
- **THEN** only guardrails-set questions are answered and reported

#### Scenario: Unknown question ID
- **WHEN** the owner asks for a question ID that isn't in either set
- **THEN** the command exits with status 1 before asking any question

### Requirement: The run paces its questions for the free tier
The evaluation command SHALL wait a configurable delay between the start of one question and the next, 5 seconds by default, so a full run stays within the model's free-tier per-minute limits. A delay of 0 SHALL be allowed.

#### Scenario: Default pacing
- **WHEN** a full run starts with the default delay
- **THEN** no two questions start less than 5 seconds apart

### Requirement: No model is called to grade answers
Scoring SHALL be deterministic. Neither the evaluation command nor the live checks SHALL make any model request beyond the requests that answering a question already makes.

#### Scenario: Cost of a run
- **WHEN** an evaluation run asks N questions
- **THEN** its only model requests are each question's embedding request and chat request, plus the client's configured retries of those

### Requirement: Runs are recorded as Datadog experiments when keys are present
When `DD_API_KEY` and `DD_APP_KEY` are both set and local mode isn't requested, each set run SHALL be recorded as a Datadog experiment in the application's project. The experiment SHALL hold each question's answer and check results, plus the chat model, embedding model, `top_k`, temperature and commit. The command SHALL print each experiment's link.

#### Scenario: Recorded run
- **GIVEN** `DD_API_KEY` and `DD_APP_KEY` are set
- **WHEN** a full run finishes
- **THEN** Datadog has one experiment per set with every question's answer, check results and the run's configuration, and the report prints a link to each

#### Scenario: Pipeline visible per question
- **WHEN** a recorded run answers a question
- **THEN** that question's record in the experiment shows the question's embedding, retrieval and chat model steps

### Requirement: Experiment datasets follow the question set contents
Each set SHALL be recorded against a Datadog dataset identified by that set's contents. A run with unchanged questions SHALL reuse the existing dataset, so its experiments can be compared. A run after the set changed SHALL use a new dataset.

#### Scenario: Two runs without edits
- **WHEN** the owner records two runs without changing the question sets
- **THEN** both runs' experiments for a set use the same dataset

#### Scenario: Question added
- **WHEN** the owner adds a question to the answers set and records a run
- **THEN** that run's answers experiment uses a new dataset that includes the new question

### Requirement: Runs without Datadog keys stay local
When `DD_API_KEY` or `DD_APP_KEY` is missing, or local mode is requested, the evaluation command SHALL send nothing to Datadog, say once that results stay local, and still print the full report.

#### Scenario: No application key
- **GIVEN** `DD_API_KEY` is set and `DD_APP_KEY` is not
- **WHEN** the owner runs the evaluation command
- **THEN** nothing is sent to Datadog, one line says the results stay local, and the report and exit status are the same as for a recorded run

### Requirement: Recording problems are found before any question is asked
When recording is on, the command SHALL prepare the Datadog project and datasets before asking the first question. If Datadog rejects the keys or can't be reached, it SHALL exit with status 1 without asking any question and without printing either key.

#### Scenario: Application key rejected
- **GIVEN** `DD_APP_KEY` is set to a key Datadog rejects
- **WHEN** the owner runs the evaluation command
- **THEN** it exits with status 1, no model request is made, and neither key appears in its output

### Requirement: The Datadog application key stays on the owner's machine
`DD_APP_KEY` SHALL be read only by the evaluation command. The deployed service SHALL NOT need or read it, the blueprint MUST NOT list it, and no output, log, span, evaluation or experiment SHALL contain its value.

#### Scenario: Blueprint contents
- **WHEN** the blueprint is inspected
- **THEN** it doesn't mention `DD_APP_KEY`, and no Datadog application key appears anywhere in the repository

#### Scenario: Web app with an application key in its environment
- **GIVEN** `DD_APP_KEY` is set in the web app's environment
- **WHEN** the web app starts with tracing on and answers a question
- **THEN** it behaves exactly as without `DD_APP_KEY`

### Requirement: Traced answers carry live answer checks
When tracing is on, each `/answer` trace SHALL carry evaluations on its root span, depending on the answer mode:
- `generated`: `retrieval_top_score` (the highest similarity score retrieved), `cites_sources` (the answer cites a retrieved passage), and `citations_valid` and `plain_text`, each with a pass or fail assessment.
- `extractive`: only `retrieval_top_score`.
- `no_results` and `error`: none.

#### Scenario: Generated answer
- **GIVEN** tracing is on and retrieval returns `skills#1` (0.82) and `experience#2` (0.77)
- **WHEN** the generated answer cites `[skills#1]` in plain text
- **THEN** the trace's root span carries `retrieval_top_score` 0.82, `cites_sources` true, `citations_valid` true with assessment pass, and `plain_text` true with assessment pass

#### Scenario: Fallback answer
- **WHEN** the chat model is unavailable and the answer is `extractive`
- **THEN** the root span carries only `retrieval_top_score`

#### Scenario: Nothing retrieved
- **WHEN** the answer mode is `no_results`
- **THEN** the trace carries no answer-check evaluations

### Requirement: Live answer checks hold no text
Live answer-check evaluations SHALL hold only numbers, booleans and pass or fail assessments. They MUST NOT hold the question, passage or answer text, or any secret, whether text capture is on or off.

#### Scenario: Text capture off
- **GIVEN** `OBSERVABILITY_CAPTURE_TEXT` is `false`
- **WHEN** a visitor asks "What can Kai do?" and gets a generated answer
- **THEN** the answer-check evaluations are still recorded, and neither the question nor the answer text appears in them

### Requirement: Live answer checks never affect requests
Live answer checks SHALL make no model or database request, SHALL NOT change any API response, and SHALL NOT fail a request. A failure to compute or send them SHALL be logged like other tracing failures and otherwise ignored.

#### Scenario: Sending an evaluation fails
- **WHEN** sending an answer-check evaluation raises an error
- **THEN** `/answer` returns the same status and body it would with tracing off

#### Scenario: Tracing off
- **GIVEN** tracing is off
- **WHEN** a question is answered
- **THEN** no answer checks are computed or sent

### Requirement: Evaluation is documented
The project README SHALL explain how to run the evaluation command and its options, which settings and keys it needs, how to create a Datadog application key and keep it local, its cost in model requests, how to read the report and the experiments, and how to add a question. The deployment guide SHALL describe the live answer checks and where to find them in Datadog.

#### Scenario: Owner records a first experiment
- **WHEN** the owner follows the README with a seeded knowledge base and a Datadog account on the free plan
- **THEN** they end with an experiment per question set in Datadog, without adding a payment method or putting `DD_APP_KEY` on the hosting service

### Requirement: Tests never contact a model, the database or Datadog
The automated tests for evaluation SHALL use test doubles for the model, the knowledge base and Datadog. They SHALL pass with no network access and no credentials, even when the developer's `.env` sets `DD_API_KEY` and `DD_APP_KEY`.

#### Scenario: Developer has keys in `.env`
- **GIVEN** the developer's `.env` sets `DD_API_KEY`, `DD_APP_KEY` and Gemini and Supabase keys
- **WHEN** the test suite runs
- **THEN** no test sends a request to Gemini, Supabase or Datadog
