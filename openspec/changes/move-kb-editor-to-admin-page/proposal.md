# Proposal

## Why

The customer chat page at `/chat` also shows the Knowledge Base Editor, so every visitor sees a panel for overwriting the knowledge base, along with a welcome message that invites them to use it. Only the owner can use it, since saving needs the admin token. It belongs on a separate admin page that asks for the token before showing anything.

## What Changes

- **New admin page at `/admin`.** The Knowledge Base Editor moves here unchanged: the Documents tab, the Settings tab and Save. The page links back to `/chat`.
- **The admin page asks for the token when it opens.** On a deployment that sets `SEED_TOKEN`, `/admin` first shows a token form. The editor appears only after the server accepts the token. The token is kept for the current browser tab only, as today. When no `SEED_TOKEN` is set (local development), the editor opens directly.
- **New token check endpoint `GET /admin/verify`.** It returns 200 when the request carries the admin token, or when no token is configured. Otherwise it returns 401. It has no side effects, so the page can check a token without seeding.
- **Rejected token while saving.** If Save gets a 401, for example because the token was rotated after the page opened, the page forgets the token and asks for it again. Unsaved edits are kept.
- **BREAKING (UI): the chat page no longer has the editor.** `/chat` becomes a full-width customer chat. It loses the editor panel, Save, the token prompt, and the welcome-message line about editing documents. It has no link to `/admin`. Anyone who seeded from `/chat` now uses `/admin`. The API is unchanged except for the new endpoint.
- **Docs.** `DEPLOYMENT.md` and the README point to `/admin` for seeding from the browser.

## Capabilities

### New Capabilities
- `admin-page`: the browser page where the owner edits and saves the knowledge base. Covers where the editor lives, how the page asks for and checks the admin token, and the absence of editing from the customer chat page.

### Modified Capabilities
- `knowledge-base-seeding`: removes the requirement "The chat page asks for the token when seeding is refused". Token handling in the browser moves to `admin-page`. `/seed` itself is unchanged. This capability is defined in `deploy-render-with-gemini`, which is merged but not yet archived, so this change must be archived after it.

## Impact

- **Code**:
  - `app/main.py`: a `GET /admin` route serving `static/admin.html`, and `GET /admin/verify` using the existing `require_seed_token` check.
  - `static/admin.html` (new): the editor, Settings tab, Save and token form, moved from the chat page.
  - `static/chat.html`: editor markup, styles and script removed; single-column layout; welcome text and page title updated.
- **API**: adds `GET /admin` (HTML) and `GET /admin/verify`. Existing endpoints are unchanged. `/chat`, `/answer`, `/healthz`, `/documents` and `/` stay public.
- **Tests**: `tests/test_api.py` gains tests for `/admin`, `/admin/verify` and the chat page no longer containing the editor. They run offline in the existing CI.
- **Docs**: `DEPLOYMENT.md` (section 4 and the public-endpoints line) and the README "Seed Knowledge Base" section.
- **Dependencies, data, deployment config**: none. No schema, `render.yaml` or environment variable changes. The existing `SEED_TOKEN` is reused.
- **Depends on**: `deploy-render-with-gemini`, which is already on `origin/main`. Implement on a new branch from `origin/main`.
