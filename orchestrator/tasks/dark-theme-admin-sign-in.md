# Task: a dark theme on every page, and an admin sign-in page

This FastAPI app (`app/main.py`) serves two pages from `static/`:
- `/chat`: the "Customer Support" page, `static/chat.html`;
- `/admin`: the "Knowledge Base Editor", `static/admin.html`.

The admin token is `SEED_TOKEN`, read as `settings.seed_token` in `app/main.py`. `None` or `""` means no token is configured (local development). `settings.environment` is `"production"` on the deployed site.

Make three changes:
- a shared dark theme for all pages;
- a sign-in page that `/admin` requires;
- `/seed` also accepting the signed-in session.

The context files `tests/test_admin_sign_in.py`, `tests/test_theme.py` and `tests/test_api.py` define the expected behavior exactly; all of them must pass. Change nothing the task doesn't ask for. Add no dependencies: use only the Python standard library, FastAPI, Starlette and pydantic. Load nothing from other sites.

## Back end

### 1. New file `app/core/admin_session.py`: a stateless signed session

Use the standard library only (`hmac`, `hashlib`). Give it exactly this interface:

```python
COOKIE_NAME = "admin_session"
SESSION_SECONDS = 8 * 60 * 60

def issue(token: str, now: float) -> str:
    """A session value issued at `now` for `token`."""

def is_valid(value: str | None, token: str, now: float) -> bool:
    """Whether `value` is a session issued for `token` less than SESSION_SECONDS ago."""
```

- **Format.** The value is `v1.<issued_at>.<signature>`:
  - `issued_at` is `int(now)`;
  - `signature` is the hex HMAC-SHA256 with the token (UTF-8) as key and `admin-session:v1:<issued_at>` as message.
- **Validity.** `is_valid` is true only when all of these hold:
  - the value has exactly that form;
  - the signature matches, compared with `hmac.compare_digest`;
  - `0 <= now - issued_at < SESSION_SECONDS`.
- **Never raises.** For `None`, `""`, malformed values and values signed with another token, `is_valid` returns `False`.
- **No token in the value.** The token itself must never appear in the value.

### 2. `app/main.py`

Every check reads `settings.seed_token` at request time, and the time from `time.time()`.

- **`admin_signed_in(request) -> bool`.** True when no token is configured, or when the `admin_session` cookie `is_valid` for `settings.seed_token`.
- **`GET /admin`** (`include_in_schema=False`).
  - Signed in: `FileResponse("static/admin.html")`.
  - Otherwise: `RedirectResponse("/admin/login", status_code=303)`.
  - Both responses carry `Cache-Control: no-store`.
- **`GET /admin/login`** (new, `include_in_schema=False`).
  - Signed in, which includes "no token configured": 303 to `/admin`.
  - Otherwise: `FileResponse("static/admin-login.html")`.
  - Both responses carry `Cache-Control: no-store`.
- **`POST /admin/login`** (new, `include_in_schema=False`).
  - **Body.** Take the `Request` and read the body yourself: `await request.json()` inside `try`/`except ValueError`. Don't use a pydantic body, because FastAPI would answer 422 and echo the input.
  - **No token configured:** answer 204 and set no cookie.
  - **Wrong token.** The body is not a JSON object whose `"token"` is a string equal to `settings.seed_token` (compare UTF-8 bytes with `hmac.compare_digest`). Then:
    - log `logger.warning("Admin sign-in failed")`, never the body or the token;
    - answer 401 with JSON `{"detail": "Admin token rejected"}` and no cookie.
  - **Correct token.** Answer `Response(status_code=204)` and set the cookie `admin_session` to `issue(token, time.time())`, with:
    - `httponly=True`, `samesite="strict"`, `path="/"`, `max_age=SESSION_SECONDS`;
    - `secure=True` only when `settings.environment == "production"`.
- **`POST /admin/logout`** (new, `include_in_schema=False`). Answer 204 and delete the `admin_session` cookie with the same `path`, `httponly`, `samesite` and `secure` attributes, whether or not a session exists.
- **`/seed`.** Replace `require_seed_token` with a dependency that allows the request when any of these holds, and otherwise answers 401 with `WWW-Authenticate: Bearer`, as now:
  - no token is configured;
  - the request has `Authorization: Bearer <SEED_TOKEN>`, compared as today;
  - the `admin_session` cookie is valid and the request's `Origin` header has a host (`urllib.parse.urlsplit(origin).netloc`) equal to the request's `Host` header. Compare hosts only, not schemes: behind the hosting proxy the app sees `http` while browsers send `https`. A missing `Origin` or `Origin: null` doesn't match.
- **Remove `GET /admin/verify`** and its docstring.
- **Keep everything else exactly as it is:** every other route, CORS, error handlers, the lifespan, and `warn_if_seed_unprotected`. Update the docstring of `/admin`.

## Front end

### 3. New file `static/theme.css`: the one shared stylesheet

- In `:root`, define exactly these tokens as `#rrggbb` values. This palette passes the contrast tests; keep it unless you have a reason:

  ```css
  --bg: #0f1117; --surface: #181b23; --surface-raised: #222632; --text: #e7e9ee; --text-muted: #a4abba;
  --accent: #8b93ff; --on-accent: #0f1117; --border: #3a4050; --danger: #ff8a8a; --success: #5fd4a0; --focus: #ffd166;
  ```

  The tests require at least 4.5:1 contrast for `--text`, `--text-muted`, `--danger` and `--success` on `--bg` and `--surface`, for `--text` and `--text-muted` on `--surface-raised`, and for `--on-accent` on `--accent`. They require at least 3:1 for `--accent` and `--focus` against `--bg`, and for `--focus` against `--surface`.
- Set `color-scheme: dark` on `:root`.
- Add base styles that the pages share:
  - `body`: `var(--bg)` background, `var(--text)` color, system font stack;
  - links in `var(--accent)`;
  - inputs and textareas on `var(--surface-raised)` with `var(--text)` and a `var(--border)` border;
  - primary buttons in `var(--accent)` with `var(--on-accent)` text;
  - an error color of `var(--danger)` and a success color of `var(--success)`;
  - `[hidden] { display: none !important; }`;
  - a visible keyboard focus rule: `:focus-visible { outline: 2px solid var(--focus); outline-offset: 2px; }`.
- Don't use `@import`, no `url()` to other sites, and no `prefers-color-scheme`: the pages are always dark, with no light mode and no toggle.

### Rules for all three pages

- **In `<head>`:** `<meta name="color-scheme" content="dark">` and `<link rel="stylesheet" href="/static/theme.css">`.
- **Colors only from the stylesheet.** No hex color values in the page's own `<style>` or `style` attributes: use `var(--…)` tokens. `rgba(…)` is fine for shadows.
- **Phone width.** Each page works at 375 px wide with no horizontal scrolling.
- **Labels.** Every control has a visible label or an `aria-label`.
- **No browser storage.** Never use `sessionStorage`, `localStorage` or `document.cookie`.

### 4. `static/chat.html`: Customer Support, dark

- Replace its own `:root` palette, its light gradient and every hex color with the shared tokens:
  - page `var(--bg)`, chat panel `var(--surface)`;
  - bot messages on `var(--surface-raised)` with `var(--text)`;
  - the visitor's messages on `var(--accent)` with `var(--on-accent)`;
  - muted text in `var(--text-muted)`.

  Fix today's low-contrast text, such as the `grey` text on dark bubbles.
- Keep the content and behavior unchanged:
  - the `<title>` and `<h1>` "Customer Support";
  - the subtitle "Chat with our AI assistant for help with orders, returns, and policies";
  - the welcome message starting "Welcome to the AI Assistant!";
  - the status line `id="status"`;
  - the input `id="messageInput"`, plus `aria-label="Your question"`;
  - the "Send" button `id="sendBtn"`;
  - the script that calls `/healthz` and `/answer`;
  - the layout.
- The page must not contain `/admin` anywhere.

### 5. New file `static/admin-login.html`: the sign-in page

- **Title.** `<title>Admin sign in</title>`, with the shared head tags from above.
- **Form.** A centered card on `var(--surface)`, holding:
  - a heading and one sentence: "Enter this deployment's admin token (SEED_TOKEN) to manage the knowledge base.";
  - `<label for="tokenInput">Admin token</label>`;
  - `<input id="tokenInput" type="password" autocomplete="current-password">`;
  - `<button type="submit">Sign in</button>`;
  - a message line `<p id="message" role="alert"></p>`;
  - a link `<a href="/chat">← Back to Customer Support</a>`.
- **On submit.** Prevent the default, then:
  - an empty input shows "Enter the admin token";
  - otherwise, `fetch("/admin/login", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({token})})`;
  - 204: `location.replace("/admin")`;
  - 401: show "Admin token rejected" and select the input;
  - another status: "Can't sign in right now. Please try again.";
  - a network error: "Can't reach the server";
  - disable the button while waiting.

### 6. `static/admin.html`: the editor, signed in

- **Colors.** Use the shared head tags. Replace its own `:root` palette, gradient and every hex color with the tokens:
  - cards on `var(--surface)`, textareas on `var(--surface-raised)`;
  - the notification and the Save states in `var(--success)` and `var(--danger)` with readable text.

  The current `--success-color`, `--error-color` and `--info-color` are never defined.
- **Remove the old token gate.** The server now serves this page only to a signed-in owner, so on load show the editor and load the documents right away. Remove all of this:
  - the "Checking access…" view;
  - the token check on load;
  - `verifyToken`, `getSeedToken`, `setSeedToken` and `SEED_TOKEN_KEY`;
  - every `sessionStorage` use;
  - every `/admin/verify` call;
  - the `Authorization` header in `postSeed`. The session cookie is sent automatically.
- **Keep the editor as it is:**
  - the tab buttons with the exact texts "Documents" and "Settings";
  - the documents from `/documents` in editable textareas;
  - Save, which sends all documents to `/seed` and reports how many were inserted;
  - the "← Back to chat" link to `/chat`.
- **Sign out.** Add a "Sign out" button to the header. It sends `POST /admin/logout`, then `location.replace("/admin/login")`.
- **Signing in again after a refused save.** When Save gets 401 (the session expired or the token changed), keep the page and the unsaved edits, and show an inline sign-in form in place of the editor:
  - the message "Your session has ended. Sign in again to save your changes.";
  - `<label for="tokenInput">Admin token</label>` with a password input;
  - a "Sign in" button and a `role="alert"` message line.

  The form posts to `/admin/login` like the sign-in page. On 204, hide the form and show the editor again with the in-memory documents (don't reload them), so the owner can press Save. On 401, show "Admin token rejected".

## Done when

- All three context test files pass.
- Nothing outside these files changed.
- The three pages are dark, readable and usable with the keyboard and at phone width.
