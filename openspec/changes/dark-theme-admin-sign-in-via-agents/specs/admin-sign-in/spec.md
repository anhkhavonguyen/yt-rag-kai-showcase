# Spec Delta

## Purpose

Signing in to and out of the admin area. Covers the sign-in page, checking the admin token (`SEED_TOKEN`), and the session that lets the owner use `/admin` without entering the token on every visit.

## ADDED Requirements

### Requirement: The sign-in page is served at /admin/login
When `SEED_TOKEN` is set and the request has no valid admin session, `GET /admin/login` SHALL return 200 with an HTML page titled "Admin sign in". It SHALL contain a password field labeled "Admin token", a "Sign in" button, a message area that screen readers announce, and a link back to `/chat`.

#### Scenario: Signed-out visitor opens the sign-in page
- **GIVEN** `SEED_TOKEN` is set
- **WHEN** `GET /admin/login` is sent without a session cookie
- **THEN** the response is 200 HTML titled "Admin sign in", with a password input labeled "Admin token" and a "Sign in" button

### Requirement: The sign-in page sends signed-in owners to the admin page
`GET /admin/login` SHALL answer 303 with `Location: /admin` when the request has a valid admin session, or when `SEED_TOKEN` is unset or empty.

#### Scenario: Already signed in
- **GIVEN** `SEED_TOKEN` is set and the request carries a valid admin session cookie
- **WHEN** `GET /admin/login` is sent
- **THEN** the response is 303 to `/admin`

#### Scenario: No token configured
- **GIVEN** `SEED_TOKEN` is unset or empty
- **WHEN** `GET /admin/login` is sent
- **THEN** the response is 303 to `/admin`

### Requirement: Signing in with the correct token starts a session
`POST /admin/login` with the JSON body `{"token": "<SEED_TOKEN>"}` SHALL answer 204 and set the admin session cookie `admin_session`. The cookie SHALL be HttpOnly, `SameSite=Strict` and `Path=/`, and SHALL also be `Secure` when `ENVIRONMENT` is `production`. The token is compared in constant time.

#### Scenario: Correct token
- **GIVEN** `SEED_TOKEN` is set
- **WHEN** `POST /admin/login` is sent with `{"token": "<SEED_TOKEN>"}`
- **THEN** the response is 204, with a `Set-Cookie` for `admin_session` marked HttpOnly, `SameSite=Strict` and `Path=/`

#### Scenario: Production cookie
- **GIVEN** `SEED_TOKEN` is set and `ENVIRONMENT` is `production`
- **WHEN** the owner signs in with the correct token
- **THEN** the `admin_session` cookie is also marked `Secure`

#### Scenario: The sign-in page uses the session
- **GIVEN** the sign-in page is open
- **WHEN** the owner enters the correct token and presses "Sign in"
- **THEN** the browser goes to `/admin` and the editor is shown

### Requirement: A wrong token starts no session
`POST /admin/login` SHALL answer 401 and set no cookie when the token is wrong, empty or missing, or the body is not the expected JSON. The response and the server log SHALL NOT contain the entered token. The sign-in page SHALL say the token was rejected and stay on the form.

#### Scenario: Wrong token
- **GIVEN** `SEED_TOKEN` is set
- **WHEN** `POST /admin/login` is sent with `{"token": "wrong"}`, `{"token": ""}`, `{}` or a body that is not JSON
- **THEN** the response is 401 with no `Set-Cookie` header, and neither the response nor the log contains the sent token

#### Scenario: Wrong token on the page
- **GIVEN** the sign-in page is open
- **WHEN** the owner enters a wrong token and presses "Sign in"
- **THEN** the page stays on the form, says the token was rejected, and announces the message to screen readers

### Requirement: Sign-in with no token configured starts no session
When `SEED_TOKEN` is unset or empty, `POST /admin/login` SHALL answer 204 and set no cookie, because the admin page is open without a session.

#### Scenario: Local development
- **GIVEN** `SEED_TOKEN` is unset
- **WHEN** `POST /admin/login` is sent with any body
- **THEN** the response is 204 with no `Set-Cookie` header

### Requirement: A session lasts 8 hours and ends when the token changes
An admin session cookie SHALL be valid only when it was issued for the current `SEED_TOKEN` and was issued less than 8 hours ago. A cookie that was altered, has expired, or was issued for an earlier `SEED_TOKEN` SHALL count as no session. The cookie SHALL NOT contain the token itself.

#### Scenario: Expired session
- **GIVEN** a session cookie issued 8 hours and 1 second ago for the current `SEED_TOKEN`
- **WHEN** it is sent with `GET /admin`
- **THEN** it counts as no session

#### Scenario: Token rotated
- **GIVEN** a session cookie issued 1 minute ago
- **AND** `SEED_TOKEN` has since been changed
- **WHEN** the cookie is sent with `GET /admin`
- **THEN** it counts as no session

#### Scenario: Altered cookie
- **GIVEN** a valid session cookie with one character changed
- **WHEN** it is sent with `GET /admin`
- **THEN** it counts as no session

#### Scenario: Token not in the cookie
- **WHEN** the owner signs in
- **THEN** the `admin_session` cookie value does not contain `SEED_TOKEN`

### Requirement: Signing out ends the session
`POST /admin/logout` SHALL answer 204 and clear the `admin_session` cookie, whether or not a session exists. The admin page SHALL have a "Sign out" button that calls it and then goes to `/admin/login`.

#### Scenario: Sign out
- **GIVEN** the owner is signed in
- **WHEN** `POST /admin/logout` is sent with the session cookie
- **THEN** the response is 204 and sets `admin_session` to expire immediately, and a following `GET /admin` without a cookie is redirected to `/admin/login`

#### Scenario: Sign out from the page
- **GIVEN** the admin page is open and signed in
- **WHEN** the owner presses "Sign out"
- **THEN** the browser shows the sign-in page
