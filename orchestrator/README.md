# Agent orchestrator

A small example of a multi-agent system. You describe a web app in plain words. A **back-end agent** writes its API, a **front-end agent** writes the page that calls it, a **reviewer agent** checks both, and an **orchestrator** routes each issue back to the agent that owns it, until the reviewer approves.

It runs on Gemini's free tier and prints every step, so you can follow the flow. The result is a small app you can run: one FastAPI file, `api.py`, that also serves one page, `index.html`.

## The flow

```
                     task (from the command line)
                          │
                          ▼
                 ┌──────────────────┐
                 │   Orchestrator   │  holds: task, api.py, index.html, latest review, round
                 └──────────────────┘
       ① task (+ last api.py │    ▲ ② api.py
          + backend issues)  ▼    │
                 ┌──────────────────┐
                 │  Back-end agent  │  "write / fix api.py"            (round 1, or backend issues)
                 └──────────────────┘
       ③ task + api.py       │    ▲ ④ index.html
         (+ last page        ▼    │
          + frontend issues) ┌──────────────────┐
                 │ Front-end agent  │  "write / fix index.html"        (round 1, frontend issues,
                 └──────────────────┘                                   or api.py changed)
       ⑤ task + api.py       │    ▲ ⑥ verdict {approved, summary,
         + index.html        ▼    │            issues: [{owner, issue}]}
                 ┌──────────────────┐
                 │  Reviewer agent  │  "review both files against the task"
                 └──────────────────┘

        Orchestrator saves round-N/, then decides:
          approved                  → stop, outcome "approved"      (exit 0)
          not approved, rounds left → next round: route issues by owner, back to ①
          not approved, last round  → stop, outcome "not approved"  (exit 2)
          any model error           → stop, outcome "failed"        (exit 1)
```

What each agent receives:

| Round | Back-end agent | Front-end agent | Reviewer |
|---|---|---|---|
| 1 | task | task, api.py | task, api.py, index.html |
| 2 and later | only if it has issues: task, its last api.py, its issues | task, current api.py, its last page, its issues (or a note that api.py changed) | task, current api.py, current index.html |

### How issues are routed

The reviewer tags every issue `backend` (api.py must change) or `frontend` (index.html must change). In the next round, the orchestrator:

1. runs the back-end agent only if there are backend issues, otherwise it keeps `api.py`;
2. runs the front-end agent with its issues, or, when it has none, because `api.py` changed and the page must follow it;
3. sends an issue with no recognized owner to both agents, so nothing is dropped.

So a round that only needs front-end fixes makes 2 model calls instead of 3.

### Who does what

- **The orchestrator decides what happens next.** It is plain Python, not a model. The routing rules and the stop decision are ordinary `if` statements in [orchestrator.py](orchestrator.py).
- **Each agent defines a job.** An agent is a fixed role prompt, one model call, and code that reads the reply ([agents.py](agents.py)).
- **The model does the work.** It writes the code or judges it. All three agents use the same model; only their prompts differ. The model remembers nothing between calls, so every call carries everything it needs.

## Set up

The orchestrator uses the same three settings as the RAG app, read from the environment or from `.env` in the folder you run it from. It doesn't need the Supabase settings.

To use Gemini's free tier, get a key from [Google AI Studio](https://aistudio.google.com) and put this in `.env`:

```
OPENAI_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
OPENAI_API_KEY=your_gemini_api_key_here
OPENAI_CHAT_MODEL=gemini-3.5-flash
```

Any other OpenAI-compatible endpoint works too. Leave `OPENAI_BASE_URL` empty to use OpenAI itself.

To try a different model without editing `.env`, set the variable in your terminal. It overrides `.env` until you remove it or close the terminal. In PowerShell:

```powershell
$env:OPENAI_CHAT_MODEL = "gemini-3.5-flash-lite"
python -m orchestrator "a to-do list app"
Remove-Item Env:OPENAI_CHAT_MODEL   # back to the model in .env
```

In bash, `OPENAI_CHAT_MODEL=gemini-3.5-flash-lite python -m orchestrator "a to-do list app"` sets it for that one command.

## Run it

From the repository root, with the dependencies from `requirements.txt` installed:

```bash
python -m orchestrator "a to-do list app"
python -m orchestrator "a counter app" --max-rounds 1
python -m orchestrator --help
```

| Option | Default | Meaning |
|---|---|---|
| `--task-file PATH` | | Read the task from this UTF-8 file instead of the command line. Use it for long tasks. Don't pass both. |
| `--max-rounds N` | `3` | Most rounds, from 1 to 10. Each round makes 2 or 3 model calls. |
| `--out-dir PATH` | `orchestrator_runs` | Folder that holds the run folders. |

### The log: the orchestrator in control

A run prints one line each time the orchestrator acts. Every line starts with the time and `orchestrator`, because the orchestrator directs the work and the agents only answer it:

| Label | Meaning |
|---|---|
| `-> agent` | The orchestrator sends the agent a job. After `sends:` it lists what goes with it. |
| `<- agent` | The agent's result comes back to the orchestrator, with how long the model call took. |
| `route` | From round 2 on: how many of the review's issues go to each builder. |
| `skip` | A builder has nothing to fix, so the orchestrator keeps its file and doesn't call it. |
| `decide` | What the orchestrator does after a review or a failure: stop, or go on to the next round. |
| `result`, `next` | The outcome, the run folder, and what to do with the result. |

A `->` line with no `<-` after it means that agent is waiting for the model.

```
14:30:05 orchestrator  == round 1 of 3 ==
14:30:05 orchestrator  -> backend   write api.py | sends: task
14:30:14 orchestrator  <- backend   api.py, 2.9 KB | 8.6 s
14:30:14 orchestrator  -> frontend  write index.html | sends: task, api.py
14:30:39 orchestrator  <- frontend  index.html, 8.7 KB | 25.2 s
14:30:39 orchestrator  -> reviewer  review api.py and index.html | sends: task, api.py, index.html
14:30:47 orchestrator  <- reviewer  changes requested (1 issue: 1 frontend): The delete buttons have no accessible label. | 7.9 s
14:30:47 orchestrator  decide       changes requested, round 1 of 3 -> round 2
14:30:47 orchestrator  == round 2 of 3 ==
14:30:47 orchestrator  route        backend: 0 issues | frontend: 1 issue
14:30:47 orchestrator  skip         backend: no issues, keeping api.py
14:30:47 orchestrator  -> frontend  fix 1 issue in index.html | sends: task, api.py, index.html, 1 issue
14:31:10 orchestrator  <- frontend  index.html, 8.8 KB | 23.1 s
14:31:10 orchestrator  -> reviewer  review api.py and index.html | sends: task, api.py, index.html
14:31:16 orchestrator  <- reviewer  approved: The API and page together meet the task. | 6.4 s
14:31:16 orchestrator  decide       approved -> stop
14:31:16 orchestrator  result       approved after 2 rounds | folder: orchestrator_runs/20261112-143005
14:31:16 orchestrator  next         cd orchestrator_runs/20261112-143005/final
14:31:16 orchestrator  next         python -m uvicorn api:app   (then open http://127.0.0.1:8000)
```

If a model call fails, the `<-` line names the agent and the error type, and the run stops:

```
14:30:39 orchestrator  -> reviewer  review api.py and index.html | sends: task, api.py, index.html
14:30:40 orchestrator  <- reviewer  failed: RateLimitError (HTTP 429) | 0.8 s
14:30:40 orchestrator  decide       reviewer failed -> stop
14:30:40 orchestrator  result       failed in round 1 | folder: orchestrator_runs/20261112-143005
```

The same lines are saved to `run.log` in the run folder. To see exactly what the orchestrator sent an agent and what came back, open that call's file in `round-N/calls/`.

`RateLimitError` means the free tier's per-minute or per-day limit was reached; some models allow only about 20 calls a day. `InternalServerError (HTTP 503)` means the model is busy. Wait and run again, or try another model for one run as shown above.

## The run folder

Every run gets its own folder, `orchestrator_runs/<YYYYMMDD-HHMMSS>/`. Files are written as soon as each step finishes, so a failed run still keeps its finished work.

| Path | Contents |
|---|---|
| `round-N/api.py` | The back end after round N. When the back-end agent was skipped, a copy of the round before. |
| `round-N/index.html` | The page after round N |
| `round-N/review.json` | `{"approved": ..., "summary": ..., "issues": [{"owner": ..., "text": ...}]}` for round N |
| `round-N/calls/NN-<agent>.md` | Every model call of round N, in order: the agent's system prompt, the message the orchestrator sent, and the reply. A failed call shows its error type instead of a reply. |
| `final/api.py`, `final/index.html` | The last app. Not written when the run failed. |
| `transcript.md` | The task, which files were written or kept each round, every verdict with its issues and owners, and the outcome |
| `run.log` | The orchestrator's log lines, exactly as printed |

Every round folder is a complete app, so you can run any of them, not only `final/`. `orchestrator_runs/` is git-ignored.

## Run the generated app

**Read `api.py` and `index.html` first.** They are code written by a model. The orchestrator only saves them; it never runs, imports or serves them.

Then, with the project's virtual environment active (it already has `fastapi` and `uvicorn`):

```bash
cd orchestrator_runs/<run>/final
python -m uvicorn api:app
```

Open http://127.0.0.1:8000. `api.py` serves the page at `/` and its API under `/api/`, so the page calls the API on the same address. The data lives in memory and is gone when you stop the server with Ctrl+C.

## Project mode: the agents change this project

With `--edit`, the agents don't build a toy app. They change files of the project you run the command from. This is how the dark theme and the admin sign-in page of this repository were built:

```bash
python -m orchestrator --task-file orchestrator/tasks/dark-theme-admin-sign-in.md \
  --edit app/main.py --edit app/core/admin_session.py \
  --edit static/theme.css --edit static/chat.html --edit static/admin-login.html --edit static/admin.html \
  --context app/core/config.py --context tests/test_api.py \
  --context tests/test_admin_sign_in.py --context tests/test_theme.py
```

| Option | Meaning |
|---|---|
| `--edit PATH` | A file the agents may change or create, relative to the current folder. The file type decides the owner: `.py` goes to the back-end agent; `.html`, `.css` and `.js` go to the front-end agent. A new file is allowed if its folder exists. At most 8 files, each at most 200 KB. Paths outside the project, in `.git/` or the run output folder, and `.env` files are refused. |
| `--context PATH` | A read-only file every agent receives with every call, such as the tests the change must pass. At most 200 KB, never written. |

The loop is the same as in app mode, with these differences:

- **What the agents get.**
  - Each builder gets the task, the context files and its own files as they stand.
  - The front-end agent also gets the back-end files, read-only.
  - The reviewer gets every `--edit` file, either with its new text and a diff against the original, or noted as unchanged.
- **How builders reply.** A builder replies with whole files, each after a `FILE: <path>` line and inside a code fence. It leaves out the files it doesn't change, and a reply with no files is fine.
- **What is never written.** A file outside the builder's own `--edit` list is not saved, and a `warning` line names it. A reply cut off in the middle of a file is a failure (`TruncatedReply`), and nothing from it is saved.
- **Who runs.**
  - A side with no `--edit` files is never called, and its issues go to the other side.
  - After round 1, the front-end agent also runs when the back-end agent changed a file.
- **Timeout.** Each model call may take up to 300 seconds, because one reply can hold several whole files.

A project-mode run never writes to the project. Its run folder holds:

| Path | Contents |
|---|---|
| `round-N/files/<path>` | Every `--edit` file as it stands after round N |
| `final/files/<path>` | The files the run ends with. Not written when the run failed. |
| `changes.diff` | The final files against the project's versions when the run started |
| `manifest.json` | The project folder, the task, each `--edit` file with its owner and the SHA-256 of its starting bytes, and the outcome. `--apply` reads it. |
| `round-N/calls/`, `run.log`, `transcript.md`, `round-N/review.json` | As in app mode |

### Read the diff, then apply

**Read `changes.diff` before you apply it.** It is code written by a model, and applying runs the tests, which runs that code.

```bash
python -m orchestrator --apply orchestrator_runs/<run>
```

Apply works from the project folder the run was made in.

**What apply refuses.** It writes nothing and exits with status 1 when:
- the run isn't a project-mode run, or wasn't approved;
- it was made in another folder;
- any `--edit` file changed since the run started.

**What apply does otherwise.**
1. It writes the final files. Each file keeps its line endings, so a CRLF file stays CRLF.
2. It runs `python -m pytest -q`.
3. If the tests pass, it lists what it changed and created, and exits 0. Review with `git diff`, then commit.
4. If the tests fail, or you press Ctrl+C, it restores every file and deletes the files it created. The run's files stay in `final/files/`.

## Exit status

| Status | Meaning |
|---|---|
| `0` | The reviewer approved the app or the change. With `--apply`: applied, and the tests passed. |
| `2` | The last round ended with changes still requested. `final/` holds the last app; the open issues are printed and are in `transcript.md`. |
| `1` | The input was invalid (no task, `--max-rounds` outside 1 to 10, no `OPENAI_API_KEY`, a refused `--edit` or `--context` path), or a model call failed. Invalid input is caught before any model call. With `--apply`: the run couldn't be applied, or the tests failed and the files were restored. |

## Read the code

Read the files in this order:

| File | What it does |
|---|---|
| [`__main__.py`](__main__.py) | Reads the command line, checks the input, creates the three agents and connects them, and turns the outcome into an exit status |
| [`orchestrator.py`](orchestrator.py) | The loop: back end, front end, reviewer, decide. Holds all the state and the routing rules, and logs every action through `DispatchLog`. |
| [`agents.py`](agents.py) | The three agents: their prompts, what they send, and how their replies are read |
| [`llm.py`](llm.py) | The model client, the only code that talks to the model. Error messages keep the error type only, never the provider's text. |
| [`recorder.py`](recorder.py) | Writes the run folder, including `run.log`, and `RecordingClient`, which saves each agent's calls |
| [`project.py`](project.py) | Project mode: checks `--edit` and `--context` paths, reads the starting files, makes diffs, and applies a run |
| [`config.py`](config.py) | The three `OPENAI_*` settings |

The tests in [`tests/test_orchestrator.py`](../tests/test_orchestrator.py) and, for project mode and `--apply`, [`tests/test_orchestrator_project.py`](../tests/test_orchestrator_project.py) run offline with a scripted fake model, so they cost nothing:

```bash
pytest tests/test_orchestrator.py tests/test_orchestrator_project.py
```

## Walkthrough screenshots

Four steps from the interactive walkthrough of one run. They show the **first version** of the flow, where a single builder agent wrote the page and the reviewer checked it. The current version splits that builder into the back-end and front-end agents, as in the diagram at the top. The orchestrator's loop, its memory, the terminal output and the run folder work the same way.

**Step 3: the orchestrator gives the builder the task.** In round 1 the builder gets only the task.

![Walkthrough step 3: the orchestrator calls the builder with only the task](docs/walkthrough/step-03-builder-gets-the-task.png)

**Step 7: the reviewer asks for changes.** Its JSON verdict lists two issues, and the orchestrator keeps it as the latest review.

![Walkthrough step 7: the reviewer returns a verdict with two issues](docs/walkthrough/step-07-reviewer-asks-for-changes.png)

**Step 9: the builder fixes its page.** In round 2 the builder gets the task, its own page v1 and the two issues.

![Walkthrough step 9: the builder receives its previous page and the issues](docs/walkthrough/step-09-builder-fixes-its-page.png)

**Step 11: the run stops and is saved.** The reviewer approved round 2, so the recorder writes the final files and the transcript, and the result goes back to the command line.

![Walkthrough step 11: the run is approved after 2 rounds and saved](docs/walkthrough/step-11-run-is-saved.png)

## Ideas for the next version

Each of these changes one part and leaves the rest alone:

- **A model as the orchestrator:** replace the loop with a model that gets "build back end", "build front end" and "review" as tools and chooses which to call.
- **A tester agent:** a fourth agent that starts the app, calls the API and loads the page, and reports what breaks. The reviewer only reads code, so it can miss bugs that only show up when the app runs.
- **A web page for the orchestrator:** pass an `on_event` function that streams each step to a browser instead of printing it.
