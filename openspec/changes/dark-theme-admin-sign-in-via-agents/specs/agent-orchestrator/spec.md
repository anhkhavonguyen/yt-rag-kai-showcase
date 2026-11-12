# Spec Delta

## MODIFIED Requirements

### Requirement: A run starts from a task description
The tool SHALL take the task as a command-line argument, or read it from the UTF-8 file given with `--task-file`. It SHALL reject the following with an error message and exit status 1, before any model call is made:
- an empty or whitespace-only task;
- a task file that is missing or can't be read;
- both a task argument and `--task-file`.

#### Scenario: Task given
- **WHEN** the user runs `python -m orchestrator "a to-do list app"`
- **THEN** the run starts and the back-end agent receives that task text

#### Scenario: Empty task
- **WHEN** the user runs the tool with an empty or whitespace-only task
- **THEN** the tool prints an error saying a task is required, exits with status 1, and makes no model call

#### Scenario: Task from a file
- **GIVEN** `orchestrator/tasks/dark-theme-admin-sign-in.md` holds a multi-paragraph task
- **WHEN** the user runs the tool with `--task-file orchestrator/tasks/dark-theme-admin-sign-in.md`
- **THEN** every agent receives the file's whole text as the task

#### Scenario: Task file problems
- **WHEN** the user passes a `--task-file` that does not exist, or passes both a task argument and `--task-file`
- **THEN** the tool prints an error naming the problem, exits with status 1, and makes no model call

### Requirement: Each step is printed as it happens
The tool SHALL print one line each time the orchestrator acts, as it happens. Each line starts with the local time and the word `orchestrator`. The orchestrator acts when it:
- starts a round;
- sends a job to an agent (`->`) or receives the agent's result (`<-`);
- skips a builder;
- routes issues;
- decides to continue or stop;
- sees a failure;
- finishes.

#### Scenario: One approved round
- **WHEN** the reviewer approves round 1
- **THEN** the output shows, in order, each line starting with the time and `orchestrator`:
  - round 1 starting;
  - `-> backend` naming the job and what it sends (the task), then `<- backend` with the file it returned, its size and how long the call took;
  - `-> frontend` with what it sends (the task and `api.py`), then `<- frontend` with the same details;
  - `-> reviewer` with what it sends, then `<- reviewer` with "approved", its summary and the call time;
  - a `decide` line saying the run stops because the reviewer approved;
  - the outcome "approved" after 1 round, with the run folder path and how to run the final app

#### Scenario: A builder is skipped
- **GIVEN** the round 1 review lists only frontend issues
- **WHEN** round 2 runs
- **THEN** the output has a `route` line saying 0 issues go to the back-end agent and 1 or more go to the front-end agent, and a line saying the back-end agent is skipped and the current `api.py` is kept

#### Scenario: Changes requested with rounds left
- **GIVEN** the round limit is 3
- **WHEN** the round 1 reviewer requests changes with 1 backend and 2 frontend issues
- **THEN** `<- reviewer` shows "changes requested", the summary and the issue count per owner, and a `decide` line says the run continues to round 2 of 3

#### Scenario: A call fails
- **WHEN** the front-end agent's model call fails with `RateLimitError (HTTP 429)`
- **THEN** a line starting with the time and `orchestrator` names the front-end agent and that error type, and a `decide` line says the run stops as failed

### Requirement: Every run is saved to its own folder
Each run SHALL write to a new folder `<out-dir>/<YYYYMMDD-HHMMSS>/`, where `--out-dir` defaults to `orchestrator_runs`. Each round gets `round-<n>/` holding `api.py` and `index.html` as they stand after that round's builders, plus `review.json` and `calls/`, which holds every model request and reply of that round, in call order. A run that ends with an app gets `final/` with both files. Every run gets `transcript.md` and `run.log`.

#### Scenario: Two rounds
- **WHEN** a run is approved in round 2
- **THEN** its folder contains:
  - `round-1/` and `round-2/`, each with `api.py`, `index.html`, `review.json` and `calls/`;
  - `final/` with `api.py` and `index.html` equal to round 2's;
  - `transcript.md`, listing the task, which agents ran in each round, each verdict with its issues and owners, and the outcome;
  - `run.log`, holding the same lines the tool printed

#### Scenario: Each call is saved
- **WHEN** round 2 calls the front-end agent and the reviewer, but not the back-end agent
- **THEN** `round-2/calls/` holds, for each of the two calls in order, the system prompt and message that were sent and the reply that came back, named with the call number and the agent

#### Scenario: Runs never overwrite each other
- **WHEN** two runs start within the same second
- **THEN** each run gets its own folder and neither overwrites the other's files

### Requirement: Agents use the configured OpenAI-compatible model
Unless `--handoff` is given, all three agents SHALL send requests to the endpoint in `OPENAI_BASE_URL` (default OpenAI endpoint when unset or empty), authenticated with `OPENAI_API_KEY`, naming the model in `OPENAI_CHAT_MODEL`. The tool SHALL NOT require any database setting. Without `--handoff`, a missing `OPENAI_API_KEY` SHALL be reported before any model call, with exit status 1.

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
- **WHEN** the user starts a run without `--handoff`
- **THEN** the tool prints that `OPENAI_API_KEY` is required, exits with status 1, and makes no model call

### Requirement: Generated code is saved, never run
A build run SHALL only write generated code to files in its run folder. It SHALL NOT execute or import the code, start a server, open it in a browser, or write outside the run folder. In project mode, generated code reaches the project only through the separate apply command.

#### Scenario: App with Python and JavaScript
- **WHEN** the agents return an `api.py` and a page containing JavaScript
- **THEN** the tool saves both to the run folder and runs, imports and serves none of it

#### Scenario: Project-mode run leaves the project untouched
- **GIVEN** a project-mode run edits `app/main.py` and `static/chat.html`
- **WHEN** the run ends approved
- **THEN** `app/main.py` and `static/chat.html` in the project are byte-for-byte unchanged

## ADDED Requirements

### Requirement: Agent calls can be answered through hand-off files
With `--handoff`, the tool SHALL call no model API. For each agent call it SHALL:
- write the agent's system prompt and message to `<run folder>/handoff/NN-<agent>.request.md`;
- wait for `NN-<agent>.reply.md`, and use that file's text as the reply.

`OPENAI_API_KEY` SHALL NOT be required. A reply that does not arrive within the wait limit SHALL stop the run as a failure of that agent. Routing, logging, the run folder and `--apply` SHALL work exactly as with a model API.

#### Scenario: A call answered through files
- **GIVEN** a run with `--handoff`
- **WHEN** the orchestrator sends the back-end agent its job
- **THEN** `handoff/01-backend.request.md` holds the back-end agent's system prompt and the message
- **AND** once `handoff/01-backend.reply.md` is written, its text is read as the back-end agent's reply, and the run goes on to the front-end agent

#### Scenario: No API key needed
- **GIVEN** `OPENAI_API_KEY` is not set
- **WHEN** the user starts a run with `--handoff`
- **THEN** the run starts, and no model API is called

#### Scenario: Reply never written
- **WHEN** no reply file appears within the wait limit
- **THEN** the run stops as a failure of that agent with the error type `HandoffTimeout`

#### Scenario: The log names where the answers come from
- **WHEN** a run starts
- **THEN** its first log line names the model and endpoint, or with `--handoff`, the hand-off folder

### Requirement: Project mode lists the files the agents may change
Each `--edit PATH` SHALL name a project file the agents may change or create, relative to the current folder. A `.py` file SHALL belong to the back-end agent, and `.html`, `.css` and `.js` files to the front-end agent. Any invalid `--edit` SHALL stop the tool with an error naming the path and the problem, and exit status 1, before any model call.

#### Scenario: Owners from file types
- **WHEN** the user passes `--edit app/main.py --edit static/chat.html --edit static/theme.css`
- **THEN** the back-end agent may change `app/main.py`, and the front-end agent may change `static/chat.html` and `static/theme.css`

#### Scenario: New file
- **GIVEN** `static/admin-login.html` does not exist, and `static/` does
- **WHEN** it is passed with `--edit`
- **THEN** the front-end agent may create it

#### Scenario: Rejected paths
- **WHEN** an `--edit` path is one of the following:
  - absolute, or outside the current folder after resolving `..` and links;
  - inside `.git/` or the run output folder;
  - a `.env` file;
  - of another file type;
  - in a folder that does not exist;
  - an existing file larger than 200 KB;
  - given twice;
  - beyond 8 `--edit` paths
- **THEN** the tool prints an error naming the path and the problem, exits with status 1, and makes no model call

### Requirement: Context files are read-only input for every agent
Each `--context PATH` SHALL name an existing project file of at most 200 KB, which every agent receives with every call. Context files SHALL never be written. A context path that is missing, too large, a `.env` file, outside the project, or also given with `--edit` SHALL stop the tool with exit status 1 before any model call.

#### Scenario: Acceptance tests as context
- **WHEN** the user passes `--context tests/test_admin_sign_in.py`
- **THEN** the back-end, front-end and reviewer agents each receive that file's path and text in every call, and the file is never changed

### Requirement: Builders return whole files by path
In project mode, a builder's reply SHALL be read as zero or more files, each labeled with its path and holding the complete new text. A returned file replaces that file. A file the builder does not return SHALL keep its current text. A file outside the builder's own `--edit` list SHALL NOT be saved, and a warning naming it SHALL be logged. Files can't be deleted.

#### Scenario: Two files returned
- **GIVEN** the front-end agent owns `static/chat.html`, `static/admin.html` and `static/theme.css`
- **WHEN** its reply holds labeled files for `static/chat.html` and `static/theme.css`
- **THEN** those two files take the new text, and `static/admin.html` keeps its current text

#### Scenario: A file it does not own
- **WHEN** the back-end agent's reply holds a file labeled `static/chat.html` or `tests/test_api.py`
- **THEN** that file is not saved, and a warning line names the agent and the path

#### Scenario: No changes needed
- **WHEN** a builder's reply holds no labeled file
- **THEN** all of its files keep their current text, and the run continues

#### Scenario: Cut-off reply
- **WHEN** a builder's reply ends inside a file, before that file's closing code fence
- **THEN** the run stops as a model failure of that builder, and no file from that reply is saved

### Requirement: Project-mode builders receive their files and issues
In project mode, every builder call SHALL carry the task, the context files and the builder's own files as they currently stand. A front-end call SHALL also carry the back-end files, read-only. From round 2 on, a builder SHALL also receive its issues, routed exactly as in app mode. The front-end agent runs again when the back-end agent changed a file, even with no issues of its own.

#### Scenario: Round 1
- **GIVEN** `--edit app/main.py --edit static/chat.html`
- **WHEN** round 1 runs
- **THEN** the back-end agent receives the task, the context files and `app/main.py`; the front-end agent then receives the task, the context files, `static/chat.html`, and `app/main.py` as the back-end agent left it

#### Scenario: Only front-end issues
- **GIVEN** the round 1 review lists only frontend issues
- **WHEN** round 2 runs
- **THEN** the back-end agent is not called, and the front-end agent receives its files as they stand after round 1, plus those issues

#### Scenario: Only one side listed
- **GIVEN** every `--edit` path is an `.html` or `.css` file
- **WHEN** a run starts
- **THEN** the back-end agent is never called, and the log says it has no files

### Requirement: The reviewer sees every changed file with its diff
In project mode, the reviewer SHALL receive the task, the context files, and for each `--edit` file either its new text with a unified diff against the project's version at the start of the run, or a note that it is unchanged.

#### Scenario: One file unchanged
- **GIVEN** after round 1 `static/chat.html` changed and `app/main.py` did not
- **WHEN** the reviewer is called
- **THEN** it receives the new `static/chat.html` with its diff, and a note that `app/main.py` is unchanged

### Requirement: Project-mode runs save files by path, a diff and a manifest
A project-mode run SHALL save:
- `round-<n>/files/<path>` for every `--edit` file as it stands after that round;
- the same files under `final/files/` when the run ends with files;
- `changes.diff`, a unified diff of the final files against the project's versions at the start of the run;
- `manifest.json`, recording the project folder, the task, each `--edit` path with its owner and a SHA-256 of its text at the start (or that it did not exist), and the outcome.

#### Scenario: Approved project run
- **WHEN** a project-mode run editing `app/main.py` and `static/chat.html` is approved in round 2
- **THEN** its folder has:
  - `round-1/files/` and `round-2/files/`, each with both paths;
  - `final/files/app/main.py` and `final/files/static/chat.html`;
  - `changes.diff`;
  - a `manifest.json` with outcome approved and both starting hashes

### Requirement: Applying copies an approved run into the project
`python -m orchestrator --apply <run-folder>` SHALL write the run's final files into the project. Before writing anything, it SHALL check each condition below and refuse with an error and exit status 1, writing nothing, if any one fails:
- the folder holds a project-mode run;
- the run was approved;
- the current folder is the run's project;
- every `--edit` file still matches its starting hash, or still does not exist.

#### Scenario: File changed since the run
- **GIVEN** an approved run whose manifest has the starting hash of `static/chat.html`
- **AND** `static/chat.html` has since been edited
- **WHEN** the user runs `--apply` on that run
- **THEN** the tool names `static/chat.html` as changed since the run, writes no file, and exits with status 1

#### Scenario: Run not approved
- **WHEN** the user runs `--apply` on a run whose outcome is "not approved" or "failed"
- **THEN** the tool says only approved runs can be applied, writes no file, and exits with status 1

#### Scenario: Apply with a task
- **WHEN** the user passes a task or `--task-file` together with `--apply`
- **THEN** the tool prints an error and exits with status 1

### Requirement: Applied changes stay only if the tests pass
After writing the files, apply SHALL run the project's offline test suite (`python -m pytest -q`) in the project folder. When it passes, apply SHALL list the changed and created files and exit 0. When it fails, apply SHALL restore every file to its text before apply, delete files apply created, print the test summary, and exit with status 1.

#### Scenario: Tests pass
- **WHEN** the applied files pass the test suite
- **THEN** the project holds the run's final files, the tool lists them, and exits with status 0

#### Scenario: Tests fail
- **GIVEN** applying creates `static/admin-login.html` and changes `app/main.py`
- **WHEN** a test fails
- **THEN** `app/main.py` is restored to its text before apply, `static/admin-login.html` is deleted, the failing test summary is printed, and the tool exits with status 1
