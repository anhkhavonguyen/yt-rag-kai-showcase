# Proposal

## Why

Nothing checks this repository automatically. The only "tests" (`test_setup.py`, `verify_rag.py`, `check_dimensions.py`) are manual scripts that need real OpenAI and Supabase credentials. The original deployment path (Google Cloud Build and Cloud Run) needs a billed Google Cloud account. The project owner has no billing account, no OpenAI key and no Cloud Build. A free CI pipeline that needs no secrets is the cheapest way to catch broken code on every push. It also gives later changes, such as keyless mode and free hosting, a safety net.

## What Changes

- Add a GitHub Actions workflow that runs on every push to `main`, on every pull request targeting `main`, and on manual dispatch.
- The workflow lints the code with ruff, runs an automated pytest suite, and checks that the Docker image still builds. It does not push or deploy the image.
- Add a pytest suite under `tests/` that replaces OpenAI, Anthropic and Supabase with test doubles. It covers the text chunker, retrieval-context preparation, citation extraction, the RAG answer flow, and the HTTP API (`/`, `/healthz`, `/seed`, `/answer`).
- Add development-only dependencies (pytest, ruff) separate from the runtime `requirements.txt`. The Docker image doesn't change.
- Fix the 11 lint findings ruff reports today: unused imports and unused local variables in `app/` and the helper scripts. Without these fixes the new lint check would fail on its first run.
- Document how to run the same checks locally, and add a CI status badge to the README.
- The CI run needs **no repository secrets and no paid services**. It also passes for pull requests from forks, where GitHub withholds secrets.

## Capabilities

### New Capabilities
- `continuous-integration`: automated checks that run on every change to the repository (triggers, required checks, the no-secrets constraint, the offline test suite, and the container build check) and how developers reproduce them locally.

### Modified Capabilities
<!-- None: no existing specs, and no application API behaviour changes. -->

## Impact

- **New files**: `.github/workflows/ci.yml`, `tests/` (conftest and test modules), `requirements-dev.txt`, ruff and pytest configuration in a new `pyproject.toml`.
- **Edited files**: lint-only fixes in `app/core/config.py`, `app/core/database.py`, `app/main.py`, `app/models/responses.py`, `app/services/rag.py`, `chatbot.py` and `verify_rag.py`. Application behaviour doesn't change. `README.md` gets a badge and a "Running checks locally" section.
- **APIs**: no change to any endpoint, request or response.
- **Dependencies**: pytest and ruff are added for development and CI only. Runtime dependencies are unchanged.
- **Systems**: the pipeline runs on GitHub-hosted runners, free for public repositories (private repositories use the account's free monthly Actions minutes). Google Cloud Build and Cloud Run are not used. `DEPLOYMENT.md` is left as is, and free hosting is a separate later change.
