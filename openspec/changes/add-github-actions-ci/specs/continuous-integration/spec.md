# Spec Delta

## Purpose

Automatically checks every change to the repository with linting, an offline test suite and a container build. It needs no paid services or secrets, so broken code is caught before it reaches `main` or a deployment.

## ADDED Requirements

### Requirement: Checks run on changes to the main branch
The CI pipeline SHALL run all checks for every push to `main`, for every pull request that targets `main`, and on manual request.

#### Scenario: Push to main
- **WHEN** a commit is pushed to `main`
- **THEN** the pipeline runs the lint, test and container build checks against that commit

#### Scenario: Pull request targeting main
- **WHEN** a pull request targeting `main` is opened or updated
- **THEN** the pipeline runs all checks against the pull request's changes and reports the result on the pull request

#### Scenario: Manual run
- **WHEN** a maintainer starts the pipeline by hand for a branch
- **THEN** the pipeline runs all checks against that branch

### Requirement: Pipeline needs no secrets or paid services
The CI pipeline MUST NOT need repository secrets, API keys or any paid service to run its checks to completion.

#### Scenario: Repository with no secrets configured
- **GIVEN** the repository has no CI secrets or variables configured
- **WHEN** the pipeline runs against correct code
- **THEN** every check runs to completion and the run succeeds

#### Scenario: Pull request from a fork
- **WHEN** a pull request is opened from a fork, where the CI platform withholds secrets
- **THEN** the pipeline runs every check, and the outcome depends only on the code

### Requirement: Pipeline has read-only repository access
The CI pipeline SHALL run with read-only access to repository contents and SHALL NOT need write permissions.

#### Scenario: Pipeline token permissions
- **WHEN** the pipeline runs
- **THEN** the credentials it is given can read repository contents but cannot push commits, create releases or change repository settings

### Requirement: Lint violations fail the pipeline
The CI pipeline SHALL run a static lint check over the project's Python code and fail when it reports any violation. Generated and virtual-environment directories are excluded.

#### Scenario: Change introduces a lint violation
- **WHEN** a change adds an unused import to a module under `app/`
- **THEN** the lint check fails and reports the file and line of the violation

#### Scenario: Clean codebase
- **WHEN** the pipeline runs on `main` after this change is applied
- **THEN** the lint check reports no violations

### Requirement: Test suite runs without real credentials or external calls
The automated test suite MUST NOT send requests to OpenAI, Anthropic or Supabase, and MUST NOT read real credentials. Every external dependency is replaced by a test double.

#### Scenario: Run in CI without credentials
- **WHEN** the test suite runs with no API keys or database credentials available
- **THEN** all tests run and pass

#### Scenario: Run on a developer machine that has a real `.env`
- **GIVEN** a developer's `.env` file contains real OpenAI or Supabase credentials
- **WHEN** the developer runs the test suite
- **THEN** the tests use placeholder settings instead of the `.env` values, and no request reaches an external AI or database service

### Requirement: RAG pipeline regressions fail the pipeline
The test suite SHALL check document chunking, retrieval-context preparation, citation extraction and the answer flow. A change that breaks any of these behaviours fails the test check.

#### Scenario: Chunking behaviour changes
- **WHEN** a change makes long documents split without overlap between consecutive chunks, or breaks sequential chunk ids (`<id>#1`, `<id>#2`, ...)
- **THEN** the test check fails

#### Scenario: Context deduplication breaks
- **WHEN** a change lets several chunks of the same document, or more than four chunks, into the context passed to the language model
- **THEN** the test check fails

#### Scenario: Citation filtering breaks
- **WHEN** a change lets an answer's citations include an id that was not in the retrieved context, or repeat an id
- **THEN** the test check fails

#### Scenario: No retrieval results
- **WHEN** a change alters the answer returned when retrieval finds no chunks, so it no longer says it lacks the information or no longer returns zero citations
- **THEN** the test check fails

### Requirement: HTTP API contract regressions fail the pipeline
The test suite SHALL exercise the HTTP endpoints `/`, `/healthz`, `/seed` and `/answer` with external services replaced by test doubles. A change that breaks their status codes or response shapes fails the test check.

#### Scenario: Answer response shape changes
- **WHEN** a change removes `text`, `citations` or `debug` from the `/answer` response
- **THEN** the test check fails

#### Scenario: Request validation is lost
- **WHEN** a change makes `/answer` accept a `top_k` outside 1 to 20 without a validation error
- **THEN** the test check fails

#### Scenario: Health reporting changes
- **WHEN** a change makes `/healthz` report `ok` while the database check reports it is unreachable
- **THEN** the test check fails

### Requirement: Container image build is verified but not published
The CI pipeline SHALL build the container image defined by the repository's Dockerfile and fail if the build fails. It SHALL NOT push the image to any registry or deploy it.

#### Scenario: Broken Dockerfile
- **WHEN** a change makes the container image fail to build
- **THEN** the container build check fails

#### Scenario: Successful run publishes nothing
- **WHEN** the pipeline succeeds
- **THEN** no image has been pushed to a registry and no environment has been deployed

### Requirement: Run status reflects every check
A pipeline run SHALL be reported as failed if any one of its checks fails, and the latest result for `main` SHALL be visible from the repository README.

#### Scenario: One check fails
- **WHEN** the lint check passes but a test fails
- **THEN** the run is reported as failed on the commit or pull request

#### Scenario: README status
- **WHEN** someone views the repository README
- **THEN** a status badge shows whether the latest pipeline run on `main` passed or failed

### Requirement: Checks can be reproduced locally
The project SHALL document commands that let a developer run the same lint and test checks locally, using only development dependencies and no credentials.

#### Scenario: Developer runs checks locally
- **WHEN** a developer installs the documented development dependencies and runs the documented commands from the repository root
- **THEN** the same lint and test checks as in CI run locally and give the same pass or fail result for the same code
