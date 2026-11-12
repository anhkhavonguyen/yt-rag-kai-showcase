# Spec Delta

## Purpose

The browser page where the owner edits and saves the knowledge base. Covers where the editor lives, how the page asks for and checks the admin token, and keeping editing off the customer chat page.

## ADDED Requirements

### Requirement: The admin page is served at /admin
`GET /admin` SHALL return the admin page as HTML with status 200, without an `Authorization` header, because browsers don't send one when navigating. The page itself carries no secrets: the token is checked by the page script, and by `/seed` when saving.

#### Scenario: Opening the admin page on a protected deployment
- **GIVEN** `SEED_TOKEN` is set
- **WHEN** `GET /admin` is sent without an `Authorization` header
- **THEN** the response is 200 with an HTML page titled "Knowledge Base Editor"

### Requirement: The admin page provides the knowledge base editor
Once access is granted, the admin page SHALL show the editor that the chat page had before this change: the Documents tab, listing the documents from `/documents` with editable text; the Settings tab; and a Save action that sends all documents to `/seed`. It SHALL link back to `/chat`.

#### Scenario: Editing and saving documents
- **GIVEN** access to the admin page has been granted
- **WHEN** the owner changes a document's text and saves
- **THEN** the page sends all documents, including the change, to `/seed` and reports how many were inserted

### Requirement: The chat page has no knowledge base editing
The customer chat page at `/chat` SHALL NOT contain the knowledge base editor, a save action, a token prompt or a link to `/admin`. Its welcome message SHALL NOT mention editing documents.

#### Scenario: Visitor opens the chat page
- **WHEN** a visitor opens `/chat`
- **THEN** the page shows only the chat, with no document editor, no Save button and no link to `/admin`

### Requirement: Token check endpoint
`GET /admin/verify` SHALL return 200 when `SEED_TOKEN` is unset or empty, or when the request carries `Authorization: Bearer <SEED_TOKEN>`. Otherwise it SHALL return 401 with `WWW-Authenticate: Bearer`. It SHALL NOT read or change the knowledge base or call the embedding or chat provider.

#### Scenario: Missing or wrong token
- **GIVEN** `SEED_TOKEN` is set
- **WHEN** `GET /admin/verify` is sent with no `Authorization` header, a different bearer token, or a non-bearer scheme
- **THEN** the response is 401 with `WWW-Authenticate: Bearer`

#### Scenario: Correct token
- **GIVEN** `SEED_TOKEN` is set
- **WHEN** `GET /admin/verify` is sent with `Authorization: Bearer <SEED_TOKEN>`
- **THEN** the response is 200

#### Scenario: No token configured
- **GIVEN** `SEED_TOKEN` is unset or empty
- **WHEN** `GET /admin/verify` is sent without an `Authorization` header
- **THEN** the response is 200

#### Scenario: Checking a token has no side effects
- **WHEN** `GET /admin/verify` is called, with any outcome
- **THEN** nothing is seeded and no embedding, chat or database call is made

### Requirement: The admin page asks for the token before showing the editor
When the admin page opens, it SHALL check its remembered token, or no token, with `/admin/verify`. If that returns 401, the page SHALL show a token form instead of the editor, and show the editor only after `/admin/verify` accepts the entered token. An accepted token SHALL be remembered for the current browser tab session only.

#### Scenario: First open on a protected deployment
- **GIVEN** `SEED_TOKEN` is set and the tab holds no token
- **WHEN** the owner opens `/admin`
- **THEN** the page shows the token form and no documents

#### Scenario: Correct token entered
- **GIVEN** the token form is shown
- **WHEN** the owner enters the correct token
- **THEN** the page shows the editor with the documents loaded

#### Scenario: Wrong token entered
- **GIVEN** the token form is shown
- **WHEN** the owner enters a token that `/admin/verify` rejects
- **THEN** the page says the token was rejected, keeps the form shown, and does not remember the token

#### Scenario: Reopening in the same tab
- **GIVEN** the owner entered the correct token earlier in this browser tab
- **WHEN** the owner reloads `/admin`
- **THEN** the editor is shown without asking for the token again

#### Scenario: Local development without a token
- **GIVEN** `SEED_TOKEN` is unset
- **WHEN** the owner opens `/admin`
- **THEN** the editor is shown without a token form

### Requirement: A token rejected while saving is asked for again
If saving from the admin page gets a 401 from `/seed`, the page SHALL forget the remembered token, say the token was rejected, and show the token form again. Unsaved edits SHALL be kept, so the owner can save them after entering a valid token.

#### Scenario: Token rotated after the page opened
- **GIVEN** the editor is shown and the owner has unsaved edits
- **AND** `SEED_TOKEN` has since been changed on the server
- **WHEN** the owner saves
- **THEN** the page shows the token form with a rejected-token message
- **AND** after the owner enters the new token, the editor shows the unsaved edits, and saving succeeds
