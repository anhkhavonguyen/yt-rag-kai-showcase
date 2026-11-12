# Spec Delta

## Purpose

Controls who may change the knowledge base through `/seed`. On a public deployment, only the owner can overwrite documents or spend embedding quota, while local development stays open.

## ADDED Requirements

### Requirement: Seeding requires the admin token when one is configured
When `SEED_TOKEN` is set, `/seed` SHALL accept a request only if it carries the header `Authorization: Bearer <SEED_TOKEN>`. Any other request SHALL get 401, and the knowledge base and embedding provider are left untouched.

#### Scenario: Missing token
- **GIVEN** `SEED_TOKEN` is set
- **WHEN** `POST /seed` is sent without an `Authorization` header
- **THEN** the response is 401, no embeddings are requested, and no chunks are written

#### Scenario: Wrong token
- **GIVEN** `SEED_TOKEN` is set
- **WHEN** `POST /seed` is sent with a bearer token that differs from `SEED_TOKEN`
- **THEN** the response is 401, and no embeddings are requested and no chunks are written

#### Scenario: Correct token
- **GIVEN** `SEED_TOKEN` is set
- **WHEN** `POST /seed` is sent with `Authorization: Bearer <SEED_TOKEN>`
- **THEN** the documents are seeded and the response reports the number inserted, as before this change

### Requirement: Seeding stays open when no token is configured
When `SEED_TOKEN` is unset or empty, `/seed` SHALL behave as before this change and accept requests without an `Authorization` header.

#### Scenario: Local development
- **GIVEN** `SEED_TOKEN` is not set
- **WHEN** `POST /seed` is sent without an `Authorization` header
- **THEN** the documents are seeded

### Requirement: Other endpoints don't need the admin token
`/answer`, `/healthz`, `/documents`, `/` and the chat page SHALL NOT require the admin token.

#### Scenario: Asking a question on a protected deployment
- **GIVEN** `SEED_TOKEN` is set
- **WHEN** `POST /answer` is sent without an `Authorization` header
- **THEN** the question is answered normally

### Requirement: The chat page asks for the token when seeding is refused
When saving documents from the chat page gets a 401, the page SHALL ask the user for the admin token, retry the save with it, and remember it only for the current browser tab session.

#### Scenario: First save on a protected deployment
- **WHEN** the user saves documents in the chat page and `/seed` responds 401
- **THEN** the page asks for the admin token and retries the save with that token as a bearer token

#### Scenario: Wrong token entered
- **WHEN** the retried save also responds 401
- **THEN** the page shows an error saying the token was rejected and forgets the remembered token

### Requirement: The CLI chatbot sends the token from its environment
When the `SEED_TOKEN` environment variable is set where the CLI chatbot runs, its `/seed` command SHALL send that token as a bearer token. When the variable is unset, it SHALL send no `Authorization` header.

#### Scenario: Seeding a deployed instance from the CLI
- **GIVEN** `SEED_TOKEN` is set in the shell running the chatbot
- **WHEN** the user runs the chatbot's `/seed` command
- **THEN** the request carries `Authorization: Bearer <SEED_TOKEN>`
