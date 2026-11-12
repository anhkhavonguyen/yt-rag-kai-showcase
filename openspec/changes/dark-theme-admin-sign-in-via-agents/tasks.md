# Tasks

The work has two phases:
- **Phase 1 (groups 2 and 3)**: the orchestrator's dispatch log and project mode, written by hand and covered by offline tests.
- **Phase 2 (groups 4 and 5)**: hand-written acceptance tests and the agents' task file, then the agents build the app part with project mode. A person reviews the diff and applies it.

Everything goes on one branch and into one pull request.

Model runs use the Gemini free tier from `.env` (`orchestrator/README.md`, "Set up"). Browser checks run the app locally with `uvicorn app.main:app`.

## 1. Branch

- [x] 1.1 Create the branch `dark-theme-admin-sign-in-via-agents` from `origin/main`, bringing along this change's planning files. Verify: `git merge-base --is-ancestor d5ae471 HEAD` succeeds, and `pytest` and `ruff check .` pass before any edits.

## 2. Orchestrator: dispatch log (spec: agent-orchestrator)

- [x] 2.1 Add `DispatchLog` to `orchestrator/orchestrator.py` (design decision 6). It takes injectable `clock` and `timer` arguments, sends every line to `on_event`, and appends it to `run.log` through a new `RunRecorder.log_line`. Switch the app-mode `Orchestrator` to it:
  - round lines;
  - `->` and `<-` for each agent, with what is sent, the result and the call time;
  - skip lines;
  - `route` from round 2 on;
  - `decide` after every review and on failure;
  - `result` and `next`.

  In `tests/test_orchestrator.py`, update the event tests to a fixed clock and timer, and add these tests:
  - one approved round: the full ordered line list;
  - a skipped builder: the `route` and skip lines;
  - changes requested with rounds left: `<- reviewer` with counts per owner, and `decide ... -> round 2`;
  - a failed call: the agent and error type, and `decide` failed;
  - `run.log` equals the printed lines.

  Verify: `pytest tests/test_orchestrator.py` passes, and every line in the tests starts with `HH:MM:SS orchestrator`.
- [x] 2.2 Add `RecordingClient` (design decision 7): one per agent, wrapping the shared client. It writes `round-N/calls/NN-<agent>.md` with the system prompt, the message and the reply, or `failed: <ErrorType>`. Wire it in `__main__.py`. Tests:
  - a two-round run where round 2 skips the back end gives `round-2/calls/01-frontend.md` and `02-reviewer.md`, holding the exact prompt, message and reply;
  - extend `test_provider_message_with_the_key_reaches_no_output_or_file` to check `run.log` and every `calls/` file.

  Verify: `pytest tests/test_orchestrator.py` passes.
- [x] 2.3 Add `--task-file PATH` to `__main__.py` (spec: "A run starts from a task description"). Tests:
  - the file's whole text reaches every agent;
  - a missing file exits 1 with no model call;
  - a task argument together with `--task-file` exits 1 with no model call.

  Verify: `pytest tests/test_orchestrator.py` passes, and `python -m orchestrator --help` lists `--task-file`.
- [x] 2.4 Update `orchestrator/README.md`:
  - replace the sample output with the dispatch-log format from design decision 6;
  - add `run.log` and `round-N/calls/` to the run folder table;
  - add `--task-file` to the options table.

  Verify with one real app-mode run, `python -m orchestrator "a counter app" --max-rounds 1`, if the free tier allows it: the printed lines and `run.log` show the orchestrator sending to and receiving from all three agents in the README format, and the `calls/` files exist. If the quota is used up, note that here and rely on the offline tests.

  Result (2026-11-12): `gemini-3.5-flash` answered HTTP 429, because its daily quota was used up by earlier runs (`20261112-204119`, failed). The first `gemini-3.5-flash-lite` run got HTTP 503 from the front-end call (`20261112-204137`, failed). The third run, `20261112-204253` on `gemini-3.5-flash-lite`, was approved in round 1. Its 11 log lines show `->`/`<-` for the back-end, front-end and reviewer agents, `decide`, `result` and `next`, and `round-1/calls/` holds `01-backend.md`, `02-frontend.md` and `03-reviewer.md`. Those first runs also showed `-> frontend` running into its text, so the label column was widened to 13 characters. The README sample is checked against the formatter.

## 3. Orchestrator: project mode and apply (spec: agent-orchestrator)

- [x] 3.1 Create `orchestrator/project.py` with the `--edit` and `--context` checks:
  - owners by file type;
  - the rejected cases from "Project mode lists the files…" and "Context files are read-only…";
  - the starting snapshot: text plus SHA-256, or "missing".

  Add a parametrized test for each rejected case, plus owner mapping, a new file whose folder exists, and a path that leaves the project after resolving `..`. Verify: `pytest tests/test_orchestrator.py` passes.
- [x] 3.2 In `orchestrator/agents.py`:
  - add the `FILE:` block parser (design decision 3);
  - add the project-mode builder and reviewer prompts (design decision 5);
  - add message builders that include the context files, the back-end files (read-only, for the front end) and per-file diffs or "unchanged" notes (for the reviewer).

  Tests:
  - two files returned;
  - a file containing an inner fence;
  - `### FILE:` and `**FILE:**` forms;
  - no files means no changes;
  - a cut-off last file raises `TruncatedReply` and saves nothing;
  - a path outside the agent's list is returned as a rejected path;
  - each message lists exactly the expected inputs.

  Verify: `pytest tests/test_orchestrator.py` passes.
- [x] 3.3 Add `ProjectOrchestrator` (design decision 4), and project-mode recorder output: `round-N/files/<path>`, `final/files/<path>`, `changes.diff` and `manifest.json`. Log lines list changed paths with `+added -removed` line counts, and add a warning line for rejected paths. Tests for the spec scenarios:
  - round 1 inputs;
  - only front-end issues;
  - the back end changed, so the front end reruns;
  - only one side listed;
  - an approved run's folder layout and manifest hashes;
  - the project's files are byte-for-byte unchanged after the run.

  Verify: `pytest tests/test_orchestrator.py` passes.
- [x] 3.4 Wire project mode into `__main__.py`:
  - `--edit` and `--context` select project mode;
  - checks run before any model call;
  - a 300-second timeout through a new `timeout` parameter on `OpenAICompatibleClient`;
  - the same exit statuses;
  - the final log line shows the `--apply` command.

  Tests: invalid `--edit` and `--context` exit 1 with no model call, and project mode uses timeout 300. Verify: `pytest` passes.
- [x] 3.5 Add `--apply RUN` (design decision 8, spec: "Applying copies…" and "Applied changes stay only if the tests pass"), with an injectable `run_tests`. Tests in a temporary project:
  - refused when the run isn't project mode, isn't approved, belongs to another project folder, has a changed file, or comes with a task (exit 1, no file written);
  - passing tests leave the final files in place and exit 0;
  - failing tests restore changed files, delete created files, and exit 1;
  - a `KeyboardInterrupt` from `run_tests` also restores.

  Verify: `pytest` passes.
- [ ] 3.6 Add a "Project mode" section to `orchestrator/README.md`:
  - `--edit` owners and limits;
  - `--context`;
  - the reply format;
  - the run folder additions;
  - reading `changes.diff`;
  - `--apply` and its checks;
  - "apply runs the tests, which run model-written code: read the diff first".

  Verify: `pytest` and `ruff check .` pass, and every option in the README appears in `python -m orchestrator --help`. Commit groups 2 and 3 together, then push. Verify: CI `lint` and `test` pass on the branch.

  Status (2026-11-12): the README section is written. Locally, `pytest` gives 223 passed and 1 skipped (the symbolic-link test, since this Windows machine can't create links), `ruff check .` passes with the pinned 0.17.4, and the README options all appear in `--help`. The work is committed as `c96f2d0` and the branch is pushed. **Still open:** CI on the branch. CI runs on pull requests and on manual dispatch, and the GitHub CLI isn't installed here, so neither can be started from this machine. The CI check is moved to the pull request in 6.1.

## 4. Acceptance tests and the agents' task (hand-written, before the run)

- [x] 4.1 Write `tests/test_admin_sign_in.py`, covering every scenario in `specs/admin-sign-in`, `specs/admin-page` and `specs/knowledge-base-seeding`:
  - use `follow_redirects=False` for every 303 check;
  - import `app.core.admin_session` directly, not with `importorskip`, so a missing module fails the run;
  - build expired and rotated-token cookies with `issue(token, now)`;
  - set `ENVIRONMENT=production` to check the `Secure` flag;
  - use `caplog` to check the token is never logged;
  - check `Origin`/`Host` matching on `/seed`, using `mock_seed` to prove nothing was seeded.

  Don't commit yet. Verify: `pytest tests/test_admin_sign_in.py` fails only because the feature is missing (an import error for `app.core.admin_session`, 404s or wrong status codes), not because of mistakes in the test code.

  Result: 3 passed (the bearer-token cases of `/seed`, which don't change), 26 failed, 21 errors. Every error is `ModuleNotFoundError: app.core.admin_session`, and every failure is a 404, a missing `Cache-Control`, a missing Sign out, or `sessionStorage` still in use. The module is imported in a fixture, not at the top, so a missing module errors the tests that need it, never skips them, and the rest of the suite still runs. Two tests passed for the wrong reason at first (one against a 404, one because `/admin` is open today), and they were tightened.
- [x] 4.2 Write `tests/test_theme.py`, covering every scenario in `specs/ui-theme` that can be checked over HTTP (design decision 11):
  - `/static/theme.css` is served as CSS;
  - the tokens are present;
  - the contrast pairs pass, computed with the WCAG formula;
  - each page links the stylesheet and declares `color-scheme: dark`;
  - each page has no hex colors in its own `<style>` or `style` attributes;
  - `theme.css` has a `:focus-visible` rule;
  - no external `src`, stylesheet or `url()`;
  - `/chat` keeps its title, heading, subtitle, welcome text, input and Send button, and has no `/admin` link.

  Don't commit yet. Verify: the file fails only because the feature is missing.

  Result: 1 failed and 28 errors, all `404 == 200` for `/static/theme.css` or `/admin/login`. The helpers were checked separately: the content checks pass on today's `chat.html`, the hex check finds its 23 hard-coded colors, and token parsing and contrast give the planned values (15.53:1 for `--text` on `--bg`).
- [x] 4.3 Update `tests/test_api.py`:
  - replace the three `/admin/verify` tests with one that expects 404;
  - move the `/admin` page test to `test_admin_sign_in.py`, as 303 without a session;
  - in `test_other_endpoints_do_not_need_the_token`, replace the `/admin` line with `/admin/login` answering 200.

  Don't commit yet. Verify: the tests unrelated to `/admin` still pass on the current code.

  Result: 23 passed. The 2 that fail are the changed ones (`/admin/verify` still answers, and `/admin/login` doesn't exist yet).
- [x] 4.4 Write `orchestrator/tasks/dark-theme-admin-sign-in.md`, the agents' task. It restates the five spec files as concrete instructions:
  - routes and status codes;
  - cookie attributes;
  - the `admin_session` interface from design decision 9;
  - the theme tokens and the suggested palette from design decision 11;
  - the content `/chat` must keep;
  - the admin page's inline sign-in after a 401, Sign out, and no token in browser storage;
  - "change nothing else; keep every existing route and test passing; add no dependencies".

  Verify: a checklist that maps each spec requirement to a line in the task file, with none missing. Commit the task file only.

  Checklist (each spec requirement, then the task-file section that states it):
  - **admin-sign-in**:
    - sign-in page served → §2 `GET /admin/login`, §5;
    - signed-in owners sent to `/admin` → §2;
    - correct token starts a session → §2 cookie attributes, §5 on 204;
    - wrong token starts no session → §2 401, no log of the token, §5 message;
    - no token configured starts no session → §2;
    - 8 hours, and ends when the token changes → §1;
    - sign out → §2 logout, §6 button.
  - **admin-page**:
    - `/admin` gated, 303, `no-store` → §2;
    - editor with Sign out and no browser storage → §6 and the rules for all three pages;
    - refused save asks to sign in again → §6;
    - REMOVED token form on load → §6 "Remove the old token gate";
    - REMOVED `/admin/verify` → §2.
  - **knowledge-base-seeding**: bearer, or cookie with matching `Origin` → §2 `/seed`.
  - **ui-theme**:
    - always dark, no toggle → §3, rules;
    - one stylesheet, no hex colors → §3, rules;
    - contrast → §3 palette and thresholds;
    - focus → §3;
    - phone width → rules;
    - nothing external → intro, §3;
    - `/chat` keeps its content → §4.

  None is missing. The `agent-orchestrator` spec is not part of the agents' task, because it was written by hand in groups 2 and 3.

## 5. Build the feature with the agents (specs: admin-sign-in, admin-page, knowledge-base-seeding, ui-theme)

- [ ] 5.1 Run the command from design decision 12. Verify:
  - the run ends "approved";
  - `run.log` shows, in every round, the orchestrator dispatching to and receiving from the back-end, front-end and reviewer agents, with `route` and `decide` lines.

  If a run fails or isn't approved, run again, with a wait, `--max-rounds 5` or another model for that run. Allow at most 3 runs in total. Record each run's folder, outcome and call count under this task.
- [ ] 5.2 Read the approved run's `changes.diff` completely, and check:
  - the cookie attributes;
  - `compare_digest` for the token and the signature;
  - the token is never logged or put in the cookie;
  - the `Origin`/`Host` check on `/seed`;
  - `/seed` is still protected;
  - no route or behavior was removed beyond `/admin/verify`;
  - no external URLs;
  - no new imports outside the standard library, FastAPI, Starlette and pydantic.

  Verify: record the findings here. A problem that must be fixed goes into the task file and triggers a new run, which counts toward the 3 runs in 5.1.
- [ ] 5.3 Run `python -m orchestrator --apply orchestrator_runs/<run>`, then `ruff check .`. Verify: apply exits 0 with the full test suite passing, including 4.1 to 4.3, and ruff passes.
- [ ] 5.4 Check in a browser, locally with `SEED_TOKEN=local-test`:
  - `/chat`, `/admin/login` and `/admin` are dark, including with DevTools emulating a light `prefers-color-scheme`;
  - no page scrolls sideways at 375 px wide;
  - Tab shows a focus outline on every control;
  - `/admin` goes to sign-in;
  - `wrong` is rejected with a message;
  - `local-test` opens the editor, and a reload stays signed in;
  - with unsaved edits, restarting with `SEED_TOKEN=local-test-2` and saving shows the inline sign-in; `local-test-2` brings back the edits;
  - Sign out goes to the sign-in page;
  - with `SEED_TOKEN` unset, `/admin` opens directly;
  - a `/chat` question gets an answer, or the usual error message when no provider is configured;
  - the browser console shows no errors.

  Verify: record the results. If a check fails, fix it with another agent run (as in 5.1 and 5.2) or by hand under 5.5.
- [ ] 5.5 Record the agents' share: list the files applied unchanged from the run, and every hand edit made afterwards with its reason, or "none". Verify: `git diff` shows no change to the applied files beyond the edits listed.
- [ ] 5.6 Copy the applied run's `run.log`, `transcript.md` and `changes.diff` to `openspec/changes/dark-theme-admin-sign-in-via-agents/agent-run/` (design decision 13). Verify: the three files are there, and searching them for the `OPENAI_API_KEY` value from `.env` finds nothing.
- [ ] 5.7 Update the docs:
  - in `DEPLOYMENT.md` section 4, the "Admin page" bullet becomes: open `/admin`, sign in with `SEED_TOKEN`, and the session lasts 8 hours or until Sign out;
  - change the public-endpoints line;
  - in the README "Seed Knowledge Base" section, describe the sign-in page;
  - in `render.yaml`, change the `SEED_TOKEN` comment to say it is used to sign in at `/admin/login` and by `chatbot.py`.

  Verify: every URL in the new text matches a route in `app/main.py`, and `grep -n -i "admin/verify\|sessionStorage\|for that browser tab" DEPLOYMENT.md README.md render.yaml` finds nothing.
- [ ] 5.8 Commit the acceptance tests, the applied app files, the docs and `agent-run/` together. Verify: `pytest` and `ruff check .` pass on the commit, and `git status` is clean.

## 6. Deploy and verify end to end (owner + implementer)

- [ ] 6.1 Push, open a pull request to `main`, and merge once `lint`, `test` and `docker-build` pass. Verify: CI on `main` passes, and Render shows the new deploy as live.
- [ ] 6.2 On the deployed URL, check the following and record the results here:
  - `curl -i https://<service>.onrender.com/admin` returns 303 with `Location: /admin/login`;
  - `curl -i https://<service>.onrender.com/admin/verify` returns 404;
  - `curl -i -X POST https://<service>.onrender.com/admin/login -H "Content-Type: application/json" -d '{"token":"wrong"}'` returns 401 with no `Set-Cookie`;
  - in a browser, the `SEED_TOKEN` from the Render dashboard signs in, and DevTools shows `admin_session` as HttpOnly, Secure and SameSite=Strict;
  - saving the default documents reports 4 inserted;
  - Sign out returns to the sign-in page;
  - `/chat` is dark and answers a question about returns with citations.

## Workflow follow-up

- Archive in this order: `add-github-actions-ci`, `deploy-render-with-gemini`, `move-kb-editor-to-admin-page`, `add-agent-orchestrator`, then this change. Its deltas modify `agent-orchestrator`, `admin-page` and `knowledge-base-seeding`, which exist in the main specs only after those changes are archived.
