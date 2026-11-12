# Spec Delta

## MODIFIED Requirements

### Requirement: Seeding requires the admin token when one is configured
When `SEED_TOKEN` is set, `/seed` SHALL accept a request only if it carries either of these:
- the header `Authorization: Bearer <SEED_TOKEN>`;
- a valid admin session cookie, together with an `Origin` header whose host matches the request's `Host` header.

Any other request SHALL get 401, and the knowledge base and embedding provider are left untouched.

#### Scenario: Missing token
- **GIVEN** `SEED_TOKEN` is set
- **WHEN** `POST /seed` is sent without an `Authorization` header and without a session cookie
- **THEN** the response is 401, no embeddings are requested, and no chunks are written

#### Scenario: Wrong token
- **GIVEN** `SEED_TOKEN` is set
- **WHEN** `POST /seed` is sent with a bearer token that differs from `SEED_TOKEN`
- **THEN** the response is 401, and no embeddings are requested and no chunks are written

#### Scenario: Correct token
- **GIVEN** `SEED_TOKEN` is set
- **WHEN** `POST /seed` is sent with `Authorization: Bearer <SEED_TOKEN>`
- **THEN** the documents are seeded and the response reports the number inserted, as before this change

#### Scenario: Signed-in admin page
- **GIVEN** `SEED_TOKEN` is set
- **WHEN** `POST /seed` is sent with a valid admin session cookie and an `Origin` whose host matches the `Host` header
- **THEN** the documents are seeded and the response reports the number inserted

#### Scenario: Session cookie from another site
- **GIVEN** `SEED_TOKEN` is set
- **WHEN** `POST /seed` is sent with a valid admin session cookie and either no `Origin` header or an `Origin` whose host differs from the `Host` header
- **THEN** the response is 401, and no embeddings are requested and no chunks are written

#### Scenario: Ended session
- **GIVEN** `SEED_TOKEN` is set
- **WHEN** `POST /seed` is sent from the same origin with a session cookie that has expired or was issued for an earlier `SEED_TOKEN`
- **THEN** the response is 401, and no embeddings are requested and no chunks are written
