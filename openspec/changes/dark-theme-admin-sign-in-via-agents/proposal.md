# Proposal

## Why

The agent orchestrator can only build standalone toy apps in `orchestrator_runs/`. It can't work on this project, so its back-end, front-end and reviewer agents can't build real features here. Its console output also shows each agent working but not the orchestrator in control: there is no line saying what it sends to which agent, what comes back, or why it routes or stops.

The app has two features ready for the agents to build:
- The Customer Support page (`/chat`) and the admin pages use a light theme. The owner wants a dark one.
- Opening `/admin` shows the page shell, then an inline token form. The owner wants a proper sign-in page, so that `/admin` itself can't be opened without signing in.

## What Changes

**Agent orchestrator**
- **Project mode.** `--edit PATH` (repeatable) lists the project files the agents may change or create. File type decides the owner: `.py` files go to the back-end agent, and `.html`, `.css` and `.js` files go to the front-end agent. `--context PATH` (repeatable) gives every agent read-only files, such as acceptance tests. `--task-file PATH` reads a long task from a file. Agents reply with whole files, labeled by path. Files outside an agent's list are never written. The reviewer gets each changed file with its diff.
- **Review, then apply.** A project-mode run writes only to its run folder, as today, and adds `changes.diff`. `python -m orchestrator --apply <run-folder>` copies an approved run's files into the project, but only if none of them changed since the run started. It then runs the offline test suite and restores the original files if any test fails.
- **The log shows the orchestrator in control.** Every line comes from the orchestrator, with a time:
  - `-> agent`: what it asks the agent to do and what it sends;
  - `<- agent`: what came back and how long it took;
  - `route` and `decide`: which issues go to which agent, and why the run continues or stops.

  The same lines go to `run.log` in the run folder. Every model request and reply is saved under `round-N/calls/`. **BREAKING (output format)**: the progress lines change for app mode too. Exit statuses and the run folder layout are unchanged; the new files are added.

**The app, built by the agents in project mode**
- **Dark theme on every page.** `/chat`, the new sign-in page and `/admin` share one dark stylesheet, `static/theme.css`. Its text colors meet WCAG AA contrast. The pages are always dark, with no light mode and no toggle.
- **Admin sign-in page at `/admin/login`.**
  - The owner signs in with the existing `SEED_TOKEN`, which sets a signed, HttpOnly session cookie that lasts 8 hours.
  - `GET /admin` without a valid session redirects to `/admin/login`. When no `SEED_TOKEN` is set (local development), `/admin` stays open.
  - The admin page gets a Sign out button.
  - Changing `SEED_TOKEN` ends every session.
- **BREAKING (API): `GET /admin/verify` is removed.** `POST /admin/login` replaces it. The admin page no longer keeps the token in `sessionStorage`.
- **`/seed` also accepts the admin session cookie** on same-origin requests. The bearer token still works, so `curl` and `chatbot.py` are unchanged.
- **No link from Customer Support to admin.** The existing rule stays.
- **Docs.** `DEPLOYMENT.md`, the README and the `render.yaml` comment describe signing in instead of entering the token on the page.

## Capabilities

### New Capabilities
- `admin-sign-in`: signing in to and out of the admin area: the sign-in page, `POST /admin/login`, `POST /admin/logout`, and the signed session cookie and how long it lasts.
- `ui-theme`: the shared dark look of every browser page: one stylesheet, its color tokens and contrast rules, the dark color scheme, and visible keyboard focus.

### Modified Capabilities
- `agent-orchestrator`:
  - project mode (editable files, context files, task file, multi-file replies, diff for the reviewer, apply step);
  - the progress output becomes an orchestrator dispatch log saved as `run.log`;
  - every model call is saved;
  - the task can come from a file;
  - "never run" now covers the build run only, and the apply step runs the tests.
- `admin-page`:
  - `/admin` requires a session and redirects to sign-in otherwise;
  - the inline token form and `/admin/verify` are removed;
  - a refused save asks the owner to sign in again;
  - the editor gets Sign out.
- `knowledge-base-seeding`: `/seed` accepts a valid admin session cookie on same-origin requests, in addition to the bearer token.

None of these capabilities is in `openspec/specs/` yet. They are defined in the merged but unarchived changes `add-agent-orchestrator`, `move-kb-editor-to-admin-page` and `deploy-render-with-gemini`, so this change must be archived after them.

## Impact

- **Code (orchestrator, hand-written)**:
  - `orchestrator/__main__.py`: new options and the apply command;
  - `orchestrator/orchestrator.py`: dispatch log and project-mode loop;
  - `orchestrator/agents.py`: project-mode prompts and multi-file replies;
  - `orchestrator/recorder.py`: `run.log`, `calls/`, `changes.diff` and `manifest.json`;
  - a new `orchestrator/project.py`: path checks, reading files, diffs, apply;
  - `orchestrator/README.md`;
  - a new task file, `orchestrator/tasks/dark-theme-admin-sign-in.md`.
- **Code (app, written by the agents, then reviewed and applied)**:
  - `app/main.py`;
  - a new `app/core/admin_session.py`;
  - `static/chat.html` and `static/admin.html`;
  - a new `static/admin-login.html`;
  - a new `static/theme.css`.
- **Tests (hand-written, before the agents run, and given to them as context)**:
  - a new `tests/test_admin_sign_in.py`;
  - a new `tests/test_theme.py`;
  - updates to `tests/test_api.py`, for `/admin/verify` and the `/admin` redirect;
  - updates to `tests/test_orchestrator.py`, for the new log and project mode.
- **API**:
  - adds `GET /admin/login`, `POST /admin/login` and `POST /admin/logout`;
  - removes `GET /admin/verify`;
  - `GET /admin` can answer 303;
  - `/seed` also accepts the session cookie.
- **Dependencies, data, deployment**: no new packages (no `python-multipart`, since sign-in posts JSON). No new environment variables or secrets: the session is signed with `SEED_TOKEN`. No schema or `render.yaml` setting changes, only a comment.
- **Model usage**: one project-mode run makes up to 9 calls on Gemini's free tier, which can hit rate limits. A failed run is simply run again.
