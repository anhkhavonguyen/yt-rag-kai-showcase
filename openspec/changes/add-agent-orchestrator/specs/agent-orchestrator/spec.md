# Spec Delta

## Purpose

Turns a plain-language description of a small web app into a reviewed FastAPI back end and a page that calls it. An orchestrator passes work between a back-end agent, a front-end agent and a reviewer agent, routes each review issue to the agent that owns it, and shows every step so the flow can be followed and studied.

## ADDED Requirements

### Requirement: A run starts from a task description
The tool SHALL take the task as a command-line argument and SHALL reject an empty or whitespace-only task with an error message and exit status 1, before any model call is made.

#### Scenario: Task given
- **WHEN** the user runs `python -m orchestrator "a to-do list app"`
- **THEN** the run starts and the back-end agent receives that task text

#### Scenario: Empty task
- **WHEN** the user runs the tool with an empty or whitespace-only task
- **THEN** the tool prints an error saying a task is required, exits with status 1, and makes no model call

### Requirement: The round limit is configurable
The tool SHALL stop after at most `--max-rounds` rounds, default 3. A value below 1 or above 10 SHALL be rejected with an error and exit status 1, before any model call.

#### Scenario: Default limit
- **WHEN** the user does not pass `--max-rounds`
- **THEN** the run allows up to 3 rounds

#### Scenario: Limit out of range
- **WHEN** the user passes `--max-rounds 0` or `--max-rounds 11`
- **THEN** the tool prints an error naming the allowed range, exits with status 1, and makes no model call

### Requirement: The back-end agent writes one FastAPI file
Each time it runs, the back-end agent SHALL ask the model for one complete FastAPI file that keeps its data in memory, serves its API under `/api/` and returns `index.html` from its own folder at `/`, and SHALL save the code from the reply as `api.py`. If the reply wraps the code in a Markdown code fence, only the code inside SHALL be kept.

#### Scenario: Reply in a code fence
- **WHEN** the back-end agent's reply is a sentence followed by the file inside a `python` code fence
- **THEN** the saved `api.py` contains only the code inside the fence, without the sentence or the fence markers

#### Scenario: Empty file
- **WHEN** the back-end agent's reply contains no code
- **THEN** the run stops as a model failure of the back-end agent

### Requirement: The front-end agent writes one page that calls the API
Each time it runs, the front-end agent SHALL receive the current `api.py`, ask the model for one complete HTML file with all CSS and JavaScript inline that calls the API with relative `/api/` URLs, and save the code from the reply as `index.html`. If the reply wraps the code in a Markdown code fence, only the code inside SHALL be kept.

#### Scenario: Round 1
- **WHEN** the front-end agent runs in round 1
- **THEN** it receives the task and the `api.py` the back-end agent wrote in that round

#### Scenario: Reply in a code fence
- **WHEN** the front-end agent's reply is a sentence followed by the page inside an `html` code fence
- **THEN** the saved `index.html` contains only the code inside the fence

#### Scenario: Reply without a fence
- **WHEN** the front-end agent's reply is the HTML document with no code fence
- **THEN** the whole reply, without leading and trailing whitespace, is saved as `index.html`

#### Scenario: Empty page
- **WHEN** the front-end agent's reply contains no code
- **THEN** the run stops as a model failure of the front-end agent

### Requirement: Issues go to the agent that owns them
After round 1, the orchestrator SHALL run the back-end agent only when the last review has backend issues, and the front-end agent only when it has frontend issues or `api.py` was rebuilt in that round. An issue with no recognized owner SHALL go to both agents. Each agent SHALL receive the task, its own file from the previous round and only its issues; the front-end agent also receives the current `api.py`.

#### Scenario: Only front-end issues
- **GIVEN** the round 1 review lists only the frontend issue "the add button has no label"
- **WHEN** round 2 runs
- **THEN** the back-end agent is not called, the round 1 `api.py` is kept, and the front-end agent receives the task, that `api.py`, the round 1 page and that issue

#### Scenario: A back-end issue
- **GIVEN** the round 1 review lists only the backend issue "POST /api/todos accepts an empty title"
- **WHEN** round 2 runs
- **THEN** the back-end agent receives the task, the round 1 `api.py` and that issue, and the front-end agent then runs with the new `api.py` and its round 1 page, with no issues of its own

#### Scenario: An issue with no owner
- **GIVEN** the round 1 review lists an issue that is tagged neither backend nor frontend
- **WHEN** round 2 runs
- **THEN** both agents run and both receive that issue

### Requirement: The reviewer returns a verdict
In each round the reviewer SHALL receive the task and that round's `api.py` and `index.html`, and return a verdict with three parts: whether the app is approved, a one-line summary, and a list of issues to fix, each tagged `backend` or `frontend` (empty when approved).

#### Scenario: App approved
- **WHEN** the reviewer finds the app meets the task
- **THEN** its verdict is approved with an empty issue list

#### Scenario: Changes requested
- **WHEN** the reviewer finds problems
- **THEN** its verdict is not approved and lists each problem as a separate issue, tagged with the agent that must fix it

### Requirement: An unreadable verdict counts as changes requested
When the reviewer's reply cannot be read as a verdict, the orchestrator SHALL treat it as not approved, use the whole reply as a single issue for both agents, print a warning, and continue the run.

#### Scenario: Reviewer replies in free text
- **WHEN** the reviewer replies "Looks mostly fine but the colors clash" instead of a verdict
- **THEN** the round's verdict is not approved with that text as an issue for both agents, a warning is printed, and the next round starts if the limit allows

### Requirement: The run stops when the reviewer approves
The orchestrator SHALL end the run as soon as a round's verdict is approved, make no further model calls, and use that round's `api.py` and `index.html` as the final app.

#### Scenario: Approved in round 2
- **GIVEN** the round limit is 3
- **WHEN** the reviewer approves the round 2 app
- **THEN** no round 3 runs, the final app is the round 2 `api.py` and `index.html`, the outcome is "approved", and the tool exits with status 0

### Requirement: The run stops at the round limit
When the last allowed round ends without approval, the orchestrator SHALL stop, use that round's files as the final app, report the outcome "not approved" with the outstanding issues and their owners, and exit with status 2.

#### Scenario: Never approved
- **GIVEN** the round limit is 3
- **WHEN** every review requests changes and lists at least one backend issue
- **THEN** the run makes exactly 9 model calls, the final app is the round 3 files, the round 3 issues are printed, and the tool exits with status 2

### Requirement: Each step is printed as it happens
The tool SHALL print a line when each round starts, when each agent starts and finishes, when a builder is skipped because it has nothing to fix, when the reviewer finishes (with its summary and issue count per owner), and a final line with the outcome, rounds used and run folder path. When the run ends with an app, it SHALL also print how to run it.

#### Scenario: One approved round
- **WHEN** the reviewer approves round 1
- **THEN** the output shows, in order: round 1 starting, back-end agent working and done, front-end agent working and done, reviewer working, reviewer approved with its summary, the outcome "approved" after 1 round with the run folder path, and how to run the final app

#### Scenario: A builder is skipped
- **GIVEN** the round 1 review lists only frontend issues
- **WHEN** round 2 runs
- **THEN** the output says the back-end agent has no issues and the current `api.py` is kept

### Requirement: Every run is saved to its own folder
Each run SHALL write to a new folder `<out-dir>/<YYYYMMDD-HHMMSS>/`, where `--out-dir` defaults to `orchestrator_runs`. Each round gets `round-<n>/` holding `api.py` and `index.html` as they stand after that round's builders, plus `review.json`. A run that ends with an app gets `final/` with both files. Every run gets `transcript.md`.

#### Scenario: Two rounds
- **WHEN** a run is approved in round 2
- **THEN** its folder contains `round-1/` and `round-2/`, each with `api.py`, `index.html` and `review.json`; `final/` with `api.py` and `index.html` equal to round 2's; and `transcript.md` listing the task, which agents ran in each round, each verdict with its issues and owners, and the outcome

#### Scenario: Runs never overwrite each other
- **WHEN** two runs start within the same second
- **THEN** each run gets its own folder and neither overwrites the other's files

### Requirement: Model failures stop the run safely
When a model call fails, times out or returns no usable text, the tool SHALL stop, print which agent failed (`backend`, `frontend` or `reviewer`) and the error type, save everything finished so far plus a transcript with outcome "failed", and exit with status 1. Printed and saved text SHALL NOT include the API key or the provider's error message.

#### Scenario: Reviewer call fails
- **GIVEN** round 1's `api.py` and `index.html` were built
- **WHEN** the reviewer's model call fails with a rate-limit error whose message contains the API key
- **THEN** the tool prints that the reviewer failed with the error type, saves `round-1/api.py`, `round-1/index.html` and `transcript.md` with outcome "failed" and no `final/`, exits with status 1, and the API key appears in neither the output nor the saved files

### Requirement: Agents use the configured OpenAI-compatible model
All three agents SHALL send requests to the endpoint in `OPENAI_BASE_URL` (default OpenAI endpoint when unset or empty), authenticated with `OPENAI_API_KEY`, naming the model in `OPENAI_CHAT_MODEL`. The tool SHALL NOT require any database setting. A missing `OPENAI_API_KEY` SHALL be reported before any model call, with exit status 1.

#### Scenario: Gemini configured
- **GIVEN** `OPENAI_BASE_URL` is the Gemini OpenAI-compatible URL and `OPENAI_CHAT_MODEL=gemini-3.5-flash`
- **WHEN** a run makes model calls
- **THEN** every call goes to the Gemini URL and names `gemini-3.5-flash`

#### Scenario: No database settings
- **GIVEN** `OPENAI_API_KEY` is set and no `SUPABASE_*` variables are set
- **WHEN** the user starts a run
- **THEN** the run starts normally

#### Scenario: Missing API key
- **GIVEN** `OPENAI_API_KEY` is not set
- **WHEN** the user starts a run
- **THEN** the tool prints that `OPENAI_API_KEY` is required, exits with status 1, and makes no model call

### Requirement: Generated code is saved, never run
The tool SHALL only write generated code to files. It SHALL NOT execute or import it, start a server, open it in a browser, or write outside the run folder.

#### Scenario: App with Python and JavaScript
- **WHEN** the agents return an `api.py` and a page containing JavaScript
- **THEN** the tool saves both to the run folder and runs, imports and serves none of it
