# Tasks

Implement on a new branch from `origin/main`, which already contains `deploy-render-with-gemini` (merge `9e03fe8`). The admin page is built first and the chat page is stripped afterwards, so there is never a commit without a working editor.

Browser checks run the app locally (`uvicorn app.main:app` with the local `.env`). Local seeding can hit Supabase row-level security when the local `.env` has the publishable key in `SUPABASE_SERVICE_ROLE_KEY`, so a successful save is verified on the deployed URL in task 3.2. Token checks and 401 paths work locally, because they fail before any database call.

## 1. Admin page and token check (spec: admin-page)

- [x] 1.1 Create branch `move-kb-editor-to-admin-page` from `origin/main`, bringing along this change's planning files. Verify: `git merge-base --is-ancestor 9e03fe8 HEAD` succeeds, and `pytest` and `ruff check .` pass before any edits.
- [x] 1.2 In `app/main.py`, add `GET /admin/verify` (`include_in_schema=False`, `dependencies=[Depends(require_seed_token)]`) returning `{"ok": true}` with no service calls. In `tests/test_api.py`, add tests:
  - 401 with `WWW-Authenticate: Bearer` for a missing, wrong and non-bearer token (parametrized like `test_seed_rejects_missing_or_wrong_token`), with `mock_seed.assert_not_awaited()`;
  - 200 with the correct token;
  - 200 with no header when `seed_token` is `None` or `""`.

  Verify: `pytest` passes.
- [x] 1.3 Create `static/admin.html`:
  - Copy the editor from `static/chat.html`: the `.editor-section` markup (Documents tab, Settings tab, Save) and its CSS (`:root` tokens, base `body`, `.editor-*`, `.tab-*`, `.document-*`, `.save-*`, `.notification`, and the keyframes it uses).
  - Copy its JS: `loadDocuments`, `renderDocuments`, `updateDocument`, `switchTab`, the `sessionStorage` token helpers, `postSeed`, `saveDocuments`, `showNotification`.
  - Set the `<title>` to "Knowledge Base Editor", and add a "← Back to chat" link to `/chat` in the header.
  - Make the layout a single centered column that works down to 768px.
  - Leave `chat.html` untouched for now.

  In `app/main.py`, add `GET /admin` (`include_in_schema=False`) returning `FileResponse("static/admin.html")`. In `tests/test_api.py`:
  - add a test that `/admin` returns 200 `text/html` containing "Knowledge Base Editor" with the `seed_token` fixture active;
  - extend `test_other_endpoints_do_not_need_the_token` with `client.get("/chat")` and `client.get("/admin")`.

  Verify: `pytest` and `ruff check .` pass, and opening `http://localhost:8000/admin` with no `SEED_TOKEN` shows the editor with the 4 default documents.
- [x] 1.4 Add the token gate to `static/admin.html` (design decision 4):
  - Add a token form (password input, Continue button, message line) and keep the editor hidden until access is granted. Fetch documents only after access is granted.
  - On load, call `/admin/verify` with the stored token, or no header if none is stored. On 200, show the editor. On 401, clear the stored token and show the form. On a network error, show the form with "Can't reach the server".
  - On submit, call `/admin/verify` with the entered token. On 200, store it and show the editor. On 401, show "Admin token rejected" and don't store it.

  Verify in a browser, with the app run locally with `SEED_TOKEN=local-test`:
  - the first open shows the form and no documents;
  - `wrong` shows "Admin token rejected";
  - `local-test` shows the editor;
  - a reload in the same tab skips the form;
  - a new tab asks again;
  - with `SEED_TOKEN` unset, the editor shows directly.
- [x] 1.5 Change Save in `static/admin.html`: on a 401 from `/seed`, clear the stored token and show the token form with "Admin token rejected — enter the current token". Keep the in-memory `documents`, and once a token is accepted, return to the editor without reloading documents. Remove the `window.prompt()` path. Verify in a browser:
  - open `/admin` with `SEED_TOKEN=local-test`, enter it, and edit a document;
  - restart the server with `SEED_TOKEN=local-test-2`, then press Save: the form shows the message;
  - enter `local-test-2`: the editor shows the edited text.
- [x] 1.6 Update the docs:
  - In `DEPLOYMENT.md` section 4, replace the "Chat page" bullet with an "Admin page" bullet: open `https://<your-service>.onrender.com/admin`, enter the `SEED_TOKEN` (remembered for that browser tab only), then save.
  - In the same file, change the public-endpoints line to say that `/admin` asks for the token when it opens.
  - In the README "Seed Knowledge Base" section, add a line pointing to `http://localhost:8000/admin` for editing and seeding in the browser.

  Verify: every URL in the new text matches a route in `app/main.py`.

## 2. Remove the editor from the chat page (spec: admin-page)

- [x] 2.1 Strip the editor from `static/chat.html`:
  - Remove the `.editor-section` markup and its CSS (`.editor-*`, `.tab-*`, `.document-*`, `.save-*`, `.notification`, the editor rules in both `@media` blocks), the notification element, and the editor JS listed in task 1.3. Change `init()` to call only `checkHealth()` and focus the input.
  - Make `.app-container` a single column with a `max-width` of about 900px.
  - Set the `<title>` to "Customer Support", and delete the welcome-message sentence about editing documents.
  - Add no link to `/admin`.

  In `tests/test_api.py`, add a test that `/chat` returns 200 HTML that contains none of "Knowledge Base Editor", "/seed" and "/admin". Verify:
  - `pytest` and `ruff check .` pass;
  - in a browser, `/chat` shows only the chat, a question still gets an answer (or the usual error message without a configured provider), the browser console has no errors, and the layout holds at 768px and 375px wide;
  - `grep -n -i "chat page" DEPLOYMENT.md README.md` finds no instructions to edit or seed from the chat page.

## 3. Deploy and verify end to end (owner + implementer)

- [ ] 3.1 Open a pull request to `main`, and merge once `lint`, `test` and `docker-build` are green. Verify: the CI run on `main` passes, and Render shows the new deploy as live.
- [ ] 3.2 On the deployed URL:
  - `curl -i https://<service>.onrender.com/admin/verify` returns 401;
  - `/chat` shows only the chat, and a question about returns gets an answer with citations;
  - `/admin` shows the token form, rejects a wrong token, and accepts the `SEED_TOKEN` from the Render dashboard;
  - saving the default documents reports 4 inserted.

  Verify: record the results under this task.

## Workflow follow-up

- Archive in this order: `add-github-actions-ci`, `deploy-render-with-gemini`, then this change. This change's `knowledge-base-seeding` delta removes a requirement that exists in the main specs only after `deploy-render-with-gemini` is archived.
