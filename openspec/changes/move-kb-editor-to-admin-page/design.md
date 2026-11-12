# Design

## Context

- `static/chat.html` is one self-contained page, with inline CSS and JS and no build step. It's a two-column grid: the chat on the left and the "📋 Knowledge Base Editor" panel (`.editor-section`) on the right. The editor code is separate from the chat code: `loadDocuments`, `renderDocuments`, `updateDocument`, `switchTab`, the `sessionStorage` token helpers, `postSeed`, `saveDocuments` and `showNotification` are used only by the editor.
- `app/main.py` serves the page with `GET /chat` → `FileResponse("static/chat.html")`, and mounts `static/` at `/static`.
- `/seed` is protected by the `require_seed_token` dependency (from `deploy-render-with-gemini`). It reads `Authorization: Bearer` through `HTTPBearer(auto_error=False)`, compares with `hmac.compare_digest`, and returns 401 with `WWW-Authenticate: Bearer`. When `SEED_TOKEN` is unset or empty, it lets every request through.
- `/documents` returns the static `DEFAULT_DOCUMENTS` and is public, so nothing the editor displays is secret.
- Tests in `tests/test_api.py` use `TestClient` without the lifespan, and an autouse fixture fails any test that reaches Supabase, OpenAI or the chat model. CI runs from the repo root, so the relative `static/...` paths resolve.
- There are no browser or JS tests in the project.

## Goals / Non-Goals

**Goals:**
- Move the editor to `/admin` as is, and remove it from `/chat` without changing chat behavior.
- Check the token when `/admin` opens, using the same `SEED_TOKEN` and the same server-side comparison as `/seed`.

**Non-Goals:**
- Server-side sessions, cookies, user accounts or rate limiting.
- Changing `/seed`, `/documents`, `/answer` or the CLI chatbot.
- Making the Settings tab show the real configuration. Its hardcoded values (`http://localhost:8000`, `gpt-4o`, …) move unchanged. That's a separate fix.
- Fixing existing `innerHTML` use in the editor and chat rendering.
- Listing `/admin` in the root `/` endpoint map or the 404 handler. `/chat` isn't listed either, and the owner chose not to advertise the admin page.

## Decisions

### 1. Split into two static pages: `static/admin.html` (new) and a slimmed `static/chat.html`
- **What:** move the editor markup, its CSS (`.editor-*`, `.tab-*`, `.document-*`, `.save-*`, `.notification`) and its JS into `static/admin.html`. `chat.html` keeps only the chat:
  - The grid becomes one column, `.app-container` gets a narrower `max-width` (about 900px), and the editor rules in the `@media` blocks go.
  - The `<title>` becomes "Customer Support".
  - The welcome-message sentence about editing documents is removed.
  - `init()` no longer calls `loadDocuments`.
- **Shared styles:** each page keeps its own copy of the `:root` color tokens and base `body` styles, about 30 duplicated lines.
- **Why:** both pages are hand-written, self-contained HTML with no build step. Two independent files keep the chat page free of admin code.
- **Rejected:**
  - A shared `static/common.css`. It would touch every chat style for little gain at two pages.
  - Hiding the editor on `/chat` with a URL flag. The admin code would still ship to every customer.

### 2. `GET /admin` serves the page openly; the gate is in the page
- **What:** `@app.get("/admin", include_in_schema=False)` returns `FileResponse("static/admin.html")`, mirroring `/chat`. The file is also reachable at `/static/admin.html`, which is fine because it contains no secrets.
- **Why:** browsers don't attach a bearer token when navigating, so the HTML can't be gated with the existing scheme. Real protection is unchanged: `/seed` rejects writes without the token. The page gate keeps the editor out of sight and checks the token up front instead of after the first save.
- **Rejected:**
  - HTTP Basic auth on `/admin`. The server would gate the HTML itself, but the browser's login dialog can't be styled or logged out of. Basic auth needs a username, which `deploy-render-with-gemini` already rejected. The token would also still have to reach `/seed` as a bearer token.
  - A `?token=` query parameter. It leaks into browser history and server logs.
  - A cookie session. It needs a signing secret and CSRF protection, a lot of new surface for a page only the owner uses.

### 3. `GET /admin/verify` reuses `require_seed_token`
- **What:** `@app.get("/admin/verify", dependencies=[Depends(require_seed_token)], include_in_schema=False)` returns `{"ok": true}`. It touches no service, so a 200 or 401 depends only on the token check. Because the dependency allows everything when `SEED_TOKEN` is unset, the page needs no separate "is a token required?" call.
- **Why:** one comparison path for `/seed` and the page gate, so they can't disagree.
- **Rejected:**
  - Probing with `POST /seed`. It overwrites the knowledge base and spends embedding quota.
  - A `GET /admin/config` that reports whether a token is configured. It's an extra endpoint and still needs a second call to check the token.

### 4. Admin page flow
- **Views:** the page has two: a token form (a password `<input>` and a "Continue" button) and the editor. Only one is visible at a time. The editor is hidden until access is granted, and documents are fetched only then.
- **On load:** read the token from `sessionStorage` (key `ytRagSeedToken`, the existing key, with every access in try/catch), then call `/admin/verify` with it, or with no header if none is stored.
  - 200: show the editor and call `loadDocuments()`.
  - 401: clear the stored token and show the form.
  - Network error: show the form with a "Can't reach the server" message, and let the owner submit again.
- **Form submit:** call `/admin/verify` with the entered token.
  - 200: store the token and show the editor.
  - 401: show "Admin token rejected" next to the form, and don't store the token.
- **Save:** `postSeed(token)` as today.
  - 401: clear the token and switch to the form with "Admin token rejected — enter the current token". The in-memory `documents` array (and so the edits) is kept. After the token is accepted, the editor shows again without reloading documents, and the owner presses Save again.
  - No automatic retry, which keeps the flow simple.
- **Why an inline form instead of `window.prompt()`:** the token is now the first thing the page asks for. A form can show a rejection message in place, and it doesn't block the page.

### 5. The chat page has no admin link
- **What:** no link or hint to `/admin` on `/chat`, as the owner chose. The admin page header has a "← Back to chat" link to `/chat`.

### 6. Tests
- **`tests/test_api.py`, offline:**
  - `/admin` returns 200 HTML containing "Knowledge Base Editor", including when `SEED_TOKEN` is set.
  - `/chat` returns 200 HTML that doesn't contain "Knowledge Base Editor", "/seed" or "/admin".
  - `/admin/verify` returns 401 with `WWW-Authenticate: Bearer` for a missing, wrong or non-bearer token, 200 for the correct token, and 200 when the token is unset (`None` or `""`). Alongside `mock_seed.assert_not_awaited()`, the autouse service blocker shows it has no side effects.
  - `test_other_endpoints_do_not_need_the_token` also checks `/chat` and `/admin`.
- **Page JS:** checked by hand in a browser (see tasks), because the project has no browser test setup. Adding one is out of scope.

## Risks / Trade-offs

- **The page gate is client-side.** Anyone can read `admin.html` or call `/documents`. → Both show only public default documents. Writes are still refused server-side by `/seed`. The design states that the gate is about visibility, not data protection.
- **`/admin/verify` lets anyone check guesses of the token.** → `/seed` already allows that today, so the exposure is the same. Render generates a long random `SEED_TOKEN`, and `hmac.compare_digest` avoids timing leaks. Rate limiting is out of scope.
- **Anyone who seeded from `/chat` won't find the editor there.** → `DEPLOYMENT.md` and the README point to `/admin`. The proposal marks the change as BREAKING (UI).
- **Local development without `SEED_TOKEN` leaves `/admin` open.** → This matches `/seed` today. The production startup warning for a missing token already exists.
- **Duplicated CSS tokens drift between pages.** → Accepted with two small pages. A shared stylesheet can come later if more pages are added.

## Migration Plan

1. Merge through a pull request whose `lint`, `test` and `docker-build` checks pass. Render auto-deploys `main` after the checks pass.
2. On the deployed URL, run the browser checks from the tasks.
3. **Rollback:** revert the pull request. There are no data, schema or environment changes, so a revert restores the old `/chat` page.
