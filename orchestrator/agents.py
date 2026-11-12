"""The three agents: the back-end developer, the front-end developer and the reviewer.

An agent is a role prompt, one model call and code that reads the reply. Agents
remember nothing between calls: the orchestrator hands them everything they need.
"""

import json
import re
from typing import Any

from pydantic import BaseModel, Field

from .llm import ModelCallError, ModelClient

# Who must fix an issue. An issue with no recognized owner goes to both builders.
BACKEND = "backend"
FRONTEND = "frontend"
BOTH = "both"

BACKEND_PROMPT = """\
You are a back-end developer. Build the API for the web app the user describes.

Rules:
- Reply with exactly one complete Python file inside one ```python code fence.
- Use FastAPI and name the application object `app`. Import only fastapi, pydantic
  and the Python standard library.
- Keep all data in memory, for example in a list or a dict. Use no database and no files.
- Put every API route under /api/ and use pydantic models for request bodies.
- Validate input and return clear HTTP errors, for example 404 when an item does not exist.
- Serve the page too: GET / must return the file index.html from the same folder as
  this file, using FileResponse and a path built from __file__. Another developer
  writes index.html.
- When you are given your previous file and a list of issues, fix every issue and
  return the full corrected file, not a list of changes."""

FRONTEND_PROMPT = """\
You are a front-end developer. Build the web page for the app the user describes.
You are given the app's back end, api.py.

Rules:
- Reply with exactly one complete HTML document inside one ```html code fence.
- Put all CSS and JavaScript inline in that one document.
- Load nothing external: no scripts, stylesheets, fonts or images from other sites.
- api.py serves this page at /, so call the API with fetch and relative URLs such as
  /api/items. Use only the routes, methods and JSON shapes that api.py defines.
- Show a readable message when a request fails.
- When you are given your previous page and a list of issues, fix every issue and
  return the full corrected page, not a list of changes."""

REVIEWER_PROMPT = """\
You are a code reviewer. You review a small web app against the task it was built for.
The app has two files: api.py, a FastAPI back end, and index.html, the page that api.py
serves at /.

Check the back end, api.py:
- it provides what the task needs, with every API route under /api/;
- it keeps its data in memory and imports only fastapi, pydantic and the standard library;
- it validates input and returns sensible HTTP errors;
- GET / returns index.html from the same folder.

Check the front end, index.html:
- it does what the task asks, using only routes, methods and JSON shapes that api.py defines;
- it has no obvious JavaScript errors and shows a message when a request fails;
- every control has a visible label or an aria-label, and the layout works on a phone-width screen;
- it loads nothing external (no scripts, stylesheets, fonts or images from other sites).

List only issues that must be fixed. Do not list style preferences or optional
improvements. Approve the app when no such issues remain.

Reply with JSON only, with no other text, in exactly this shape:
{"approved": false, "summary": "one sentence", "issues": [{"owner": "backend", "issue": "what to fix"}]}
"owner" is "backend" when api.py must change and "frontend" when index.html must change.
"issues" is an empty list when the app is approved."""

# An opening ``` fence with an optional language tag, then everything up to the
# closing fence, or to the end of the reply if the model was cut off.
_FENCE = re.compile(r"```[ \t]*([\w+-]*)[^\n]*\n(.*?)(?:```|\Z)", re.DOTALL)
_LANGUAGE_TAGS = {"python": {"python", "py"}, "html": {"html"}}


def extract_code(reply: str, language: str) -> str:
    """Return the code from a builder's reply.

    Takes the first fence tagged with `language`, else the first fence of any
    kind, else the whole reply. Raises ModelCallError("EmptyCode") when no code is left.
    """
    fences = _FENCE.findall(reply)
    tags = _LANGUAGE_TAGS.get(language, {language})
    tagged = [body for tag, body in fences if tag.lower() in tags]
    if tagged:
        code = tagged[0]
    elif fences:
        code = fences[0][1]
    else:
        code = reply
    code = code.strip()
    if not code:
        raise ModelCallError("EmptyCode")
    return code


def _bullets(issues: list[str]) -> str:
    return "\n".join(f"- {issue}" for issue in issues)


def backend_message(task: str, previous_api: str | None = None, issues: list[str] | None = None) -> str:
    """What the back-end agent is sent: the task, plus its last api.py and its issues after round 1."""
    if previous_api is None:
        return f"Task: {task}"
    return (
        f"Task: {task}\n\n"
        f"Your previous api.py:\n```python\n{previous_api}\n```\n\n"
        f"The reviewer found these issues. Fix every one and return the full file:\n{_bullets(issues or [])}"
    )


def frontend_message(task: str, api: str, previous_page: str | None = None, issues: list[str] | None = None) -> str:
    """What the front-end agent is sent: the task and the current api.py, plus its last page after round 1."""
    parts = [f"Task: {task}", f"The back end, api.py:\n```python\n{api}\n```"]
    if previous_page is not None:
        parts.append(f"Your previous index.html:\n```html\n{previous_page}\n```")
        if issues:
            parts.append(f"The reviewer found these issues. Fix every one and return the full page:\n{_bullets(issues)}")
        else:
            parts.append("api.py has changed. Update the page so it works with the new api.py, and return the full page.")
    return "\n\n".join(parts)


def reviewer_message(task: str, api: str, page: str) -> str:
    """What the reviewer is sent: the task and both files, nothing else."""
    return f"Task: {task}\n\napi.py:\n```python\n{api}\n```\n\nindex.html:\n```html\n{page}\n```"


class Issue(BaseModel):
    """One thing the reviewer wants fixed, and who must fix it."""

    owner: str  # BACKEND, FRONTEND or BOTH
    text: str


class Review(BaseModel):
    """The reviewer's verdict on one round's app."""

    approved: bool
    summary: str
    issues: list[Issue] = Field(default_factory=list)
    # False when the reply could not be read as a verdict. Not saved in review.json.
    readable: bool = Field(default=True, exclude=True)


class _WrittenVerdict(BaseModel):
    """The verdict as the reviewer wrote it: issues may be objects or plain strings."""

    approved: bool
    summary: str
    issues: list[dict[str, Any] | str] = Field(default_factory=list)


def normalize_owner(owner: Any) -> str:
    """Map an owner such as "Back-end" or "FRONTEND" to BACKEND or FRONTEND; anything else to BOTH."""
    key = re.sub(r"[\s_-]", "", str(owner or "")).lower()
    return key if key in (BACKEND, FRONTEND) else BOTH


def _to_issue(item: dict[str, Any] | str) -> Issue:
    if isinstance(item, str):
        return Issue(owner=BOTH, text=item)
    text = item.get("issue") or item.get("text") or item.get("description")
    if not isinstance(text, str) or not text.strip():
        text = json.dumps(item, ensure_ascii=False)
    return Issue(owner=normalize_owner(item.get("owner")), text=text)


def parse_review(reply: str) -> Review:
    """Read the reviewer's reply as a verdict.

    Accepts bare JSON, JSON in a code fence, or JSON with text around it. Any
    other reply counts as "changes requested", with the whole reply as one issue
    for both builders.
    """
    text = reply.strip()
    candidates = [body.strip() for _, body in _FENCE.findall(text)[:1]]
    candidates.append(text)
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        candidates.append(text[start:end + 1])

    for candidate in candidates:
        try:
            written = _WrittenVerdict.model_validate(json.loads(candidate))
        except ValueError:  # bad JSON (JSONDecodeError) or wrong shape (ValidationError)
            continue
        return Review(
            approved=written.approved,
            summary=written.summary,
            issues=[_to_issue(item) for item in written.issues],
        )

    return Review(
        approved=False,
        summary="The reviewer's reply was not a valid verdict.",
        issues=[Issue(owner=BOTH, text=text)],
        readable=False,
    )


def _write_code(agent_name: str, client: ModelClient, system: str, user: str, language: str) -> str:
    """One model call that must return code; failures are tagged with the agent's name."""
    try:
        return extract_code(client.complete(system, user), language)
    except ModelCallError as error:
        error.agent = agent_name  # so the output can say who failed
        raise


class BackendAgent:
    """Writes api.py: the FastAPI back end, which also serves the page."""

    name = BACKEND

    def __init__(self, client: ModelClient):
        self.client = client

    def build(self, task: str, previous_api: str | None = None, issues: list[str] | None = None) -> str:
        message = backend_message(task, previous_api, issues)
        return _write_code(self.name, self.client, BACKEND_PROMPT, message, "python")


class FrontendAgent:
    """Writes index.html: one self-contained page that calls the API in api.py."""

    name = FRONTEND

    def __init__(self, client: ModelClient):
        self.client = client

    def build(
        self, task: str, api: str, previous_page: str | None = None, issues: list[str] | None = None
    ) -> str:
        message = frontend_message(task, api, previous_page, issues)
        return _write_code(self.name, self.client, FRONTEND_PROMPT, message, "html")


class ReviewerAgent:
    """Judges both files against the task and returns a Review with owner-tagged issues."""

    name = "reviewer"

    def __init__(self, client: ModelClient):
        self.client = client

    def review(self, task: str, api: str, page: str) -> Review:
        try:
            reply = self.client.complete(REVIEWER_PROMPT, reviewer_message(task, api, page))
        except ModelCallError as error:
            error.agent = self.name  # so the output can say the reviewer failed
            raise
        return parse_review(reply)
