# Spec Delta

## MODIFIED Requirements

### Requirement: The admin page is served at /admin
`GET /admin` SHALL return the admin page as HTML with status 200 only when the request carries a valid admin session, or when `SEED_TOKEN` is unset or empty. Otherwise it SHALL answer 303 with `Location: /admin/login`, and the response SHALL NOT contain the editor. Both answers SHALL carry `Cache-Control: no-store`.

#### Scenario: Opening the admin page on a protected deployment
- **GIVEN** `SEED_TOKEN` is set
- **WHEN** `GET /admin` is sent without a session cookie
- **THEN** the response is 303 to `/admin/login`, with `Cache-Control: no-store`

#### Scenario: Signed in
- **GIVEN** `SEED_TOKEN` is set
- **WHEN** `GET /admin` is sent with a valid admin session cookie
- **THEN** the response is 200 with an HTML page titled "Knowledge Base Editor"

#### Scenario: Local development without a token
- **GIVEN** `SEED_TOKEN` is unset or empty
- **WHEN** `GET /admin` is sent without a session cookie
- **THEN** the response is 200 with the editor page

### Requirement: The admin page provides the knowledge base editor
The admin page SHALL show the knowledge base editor:
- the Documents tab, listing the documents from `/documents` with editable text;
- the Settings tab;
- a Save action that sends all documents to `/seed`, using the session rather than a token held by the page;
- a link back to `/chat`;
- a "Sign out" button.

#### Scenario: Editing and saving documents
- **GIVEN** the owner is signed in on the admin page
- **WHEN** the owner changes a document's text and saves
- **THEN** the page sends all documents, including the change, to `/seed` and reports how many were inserted

#### Scenario: No token in browser storage
- **WHEN** the owner signs in, edits and saves
- **THEN** the admin token is not kept in `sessionStorage`, `localStorage` or a cookie readable by scripts

### Requirement: A token rejected while saving is asked for again
If saving from the admin page gets a 401 from `/seed`, the page SHALL say the session has ended and show a sign-in form on the page, without leaving it. Unsaved edits SHALL be kept. After the owner signs in with the current token, the page SHALL return to the editor with the edits, so they can be saved.

#### Scenario: Token rotated after the page opened
- **GIVEN** the editor is shown and the owner has unsaved edits
- **AND** `SEED_TOKEN` has since been changed on the server
- **WHEN** the owner saves
- **THEN** the page shows the sign-in form with a message that the session has ended
- **AND** after the owner enters the new token, the editor shows the unsaved edits, and saving succeeds

#### Scenario: Session expired
- **GIVEN** the editor has been open for more than 8 hours with unsaved edits
- **WHEN** the owner saves
- **THEN** the page shows the sign-in form, and after signing in again the edits are still there

## REMOVED Requirements

### Requirement: The admin page asks for the token before showing the editor
**Reason**: The server now refuses `/admin` without a session and redirects to the separate sign-in page at `/admin/login` (see `admin-sign-in`). The page no longer shows a token form on load, and no longer remembers the token in `sessionStorage`.
**Migration**: Sign in at `/admin/login` with the same `SEED_TOKEN`. The session lasts 8 hours or until Sign out.

### Requirement: Token check endpoint
**Reason**: The admin page no longer checks tokens itself. `POST /admin/login` checks the token and starts a session, so `GET /admin/verify` is removed.
**Migration**: To check a token from a script, call `POST /admin/login` with `{"token": "..."}`: 204 means correct, and 401 means wrong. `POST /seed` with a bearer token is unchanged.
