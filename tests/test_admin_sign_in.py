"""Admin sign-in, the admin page behind it, and /seed with a session.

Covers the specs admin-sign-in, admin-page and knowledge-base-seeding of the change
dark-theme-admin-sign-in-via-agents. The pages are checked as HTML; behavior that
needs a browser (focus, layout, the inline sign-in after a 401) is checked by hand.

The session interface the app must provide, in app/core/admin_session.py:

    COOKIE_NAME = "admin_session"
    SESSION_SECONDS = 8 * 60 * 60
    issue(token: str, now: float) -> str
    is_valid(value: str | None, token: str, now: float) -> bool

The app reads SEED_TOKEN from app.main.settings on every request, and the time from
time.time(), so these tests set the token with monkeypatch and build cookies with issue().
"""

import importlib
import logging
import time
from html.parser import HTMLParser
from unittest.mock import AsyncMock

import pytest

import app.main

ADMIN_TOKEN = "s3cret-admin-token-7f3a"
WRONG_TOKEN = "wrong-token-XYZ-123"
HOST = "testserver"  # the Host header TestClient sends


@pytest.fixture
def session():
    """The session module. Imported here, so its absence fails these tests only."""
    return importlib.import_module("app.core.admin_session")


@pytest.fixture
def seed_token(monkeypatch):
    monkeypatch.setattr(app.main.settings, "seed_token", ADMIN_TOKEN)
    return ADMIN_TOKEN


@pytest.fixture(params=[None, ""], ids=["unset", "empty"])
def no_seed_token(request, monkeypatch):
    monkeypatch.setattr(app.main.settings, "seed_token", request.param)


@pytest.fixture
def mock_seed(monkeypatch):
    mock = AsyncMock(return_value=4)
    monkeypatch.setattr(app.main.rag_service, "seed_documents", mock)
    return mock


def cookie(session, token=ADMIN_TOKEN, age_seconds=60.0) -> str:
    """A session cookie value issued `age_seconds` ago for `token`."""
    return session.issue(token, time.time() - age_seconds)


def with_session(value: str, **headers) -> dict:
    return {"Cookie": f"admin_session={value}", **headers}


def set_cookies(response) -> list[str]:
    return response.headers.get_list("set-cookie")


def session_cookie_header(response) -> str:
    (header,) = [h for h in set_cookies(response) if h.startswith("admin_session=")]
    return header


def attributes(header: str) -> set[str]:
    """The cookie attributes, lowercased, such as {"httponly", "samesite=strict", "path=/"}."""
    return {part.strip().lower() for part in header.split(";")[1:]}


class Page(HTMLParser):
    """Collects a page's elements (tag, attributes, text) to check labels and controls."""

    def __init__(self, html: str):
        super().__init__()
        self.elements: list[dict] = []
        self._open: list[dict] = []
        self.title = ""
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        element = {"tag": tag, "attrs": dict(attrs), "text": ""}
        self.elements.append(element)
        if tag not in ("input", "meta", "link", "br", "img"):
            self._open.append(element)

    def handle_endtag(self, tag):
        for i in range(len(self._open) - 1, -1, -1):
            if self._open[i]["tag"] == tag:
                del self._open[i:]
                break

    def handle_data(self, data):
        for element in self._open:
            element["text"] += data
        if self._open and self._open[-1]["tag"] == "title":
            self.title += data

    def find(self, tag, **attrs) -> list[dict]:
        return [e for e in self.elements if e["tag"] == tag and all(e["attrs"].get(k) == v for k, v in attrs.items())]

    def labeled_input(self, label_text: str) -> dict | None:
        """The input labeled `label_text`, by <label for> or aria-label."""
        for label in self.find("label"):
            if label["text"].strip() == label_text and label["attrs"].get("for"):
                matches = self.find("input", id=label["attrs"]["for"])
                if matches:
                    return matches[0]
        matches = [e for e in self.find("input") if e["attrs"].get("aria-label") == label_text]
        return matches[0] if matches else None

    def button(self, text: str) -> dict | None:
        matches = [e for e in self.find("button") if e["text"].strip() == text]
        return matches[0] if matches else None


# --- The sign-in page ------------------------------------------------------------------


def test_sign_in_page_for_a_signed_out_visitor(client, seed_token):
    response = client.get("/admin/login", follow_redirects=False)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    page = Page(response.text)
    assert page.title.strip() == "Admin sign in"
    token_input = page.labeled_input("Admin token")
    assert token_input is not None and token_input["attrs"].get("type") == "password"
    assert page.button("Sign in") is not None
    announced = [e for e in page.elements
                 if e["attrs"].get("role") in ("alert", "status") or e["attrs"].get("aria-live") in ("polite", "assertive")]
    assert announced, "the sign-in page needs a message area that screen readers announce"
    assert page.find("a", href="/chat")
    assert "/admin/login" in response.text  # the page signs in through POST /admin/login


def test_sign_in_page_sends_a_signed_in_owner_to_the_admin_page(client, seed_token, session):
    response = client.get("/admin/login", headers=with_session(cookie(session)), follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/admin"


def test_sign_in_page_without_a_configured_token_goes_to_the_admin_page(client, no_seed_token):
    response = client.get("/admin/login", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/admin"


# --- Signing in -----------------------------------------------------------------------------


def test_correct_token_starts_a_session(client, seed_token):
    response = client.post("/admin/login", json={"token": ADMIN_TOKEN})

    assert response.status_code == 204
    header = session_cookie_header(response)
    assert {"httponly", "samesite=strict", "path=/"} <= attributes(header)
    assert "secure" not in attributes(header)  # not production
    assert ADMIN_TOKEN not in header  # the token itself is never in the cookie


def test_production_session_cookie_is_secure(client, seed_token, monkeypatch):
    monkeypatch.setattr(app.main.settings, "environment", "production")

    response = client.post("/admin/login", json={"token": ADMIN_TOKEN})

    assert response.status_code == 204
    assert "secure" in attributes(session_cookie_header(response))


def test_signing_in_opens_the_admin_page(client, seed_token):
    assert client.get("/admin", follow_redirects=False).status_code == 303  # signed out
    assert client.post("/admin/login", json={"token": ADMIN_TOKEN}).status_code == 204  # the client keeps the cookie

    response = client.get("/admin", follow_redirects=False)

    assert response.status_code == 200
    assert "<title>Knowledge Base Editor</title>" in response.text


@pytest.mark.parametrize("request_kwargs", [
    {"json": {"token": WRONG_TOKEN}},
    {"json": {"token": ""}},
    {"json": {}},
    {"json": {"token": 12345}},
    {"json": [WRONG_TOKEN]},
    {"content": f"token={WRONG_TOKEN}", "headers": {"Content-Type": "application/x-www-form-urlencoded"}},
    {"content": WRONG_TOKEN, "headers": {"Content-Type": "application/json"}},
], ids=["wrong", "empty", "missing", "not-a-string", "not-an-object", "form-body", "not-json"])
def test_wrong_token_or_body_starts_no_session(client, seed_token, caplog, request_kwargs):
    with caplog.at_level(logging.DEBUG):
        response = client.post("/admin/login", **request_kwargs)

    assert response.status_code == 401
    assert set_cookies(response) == []
    assert WRONG_TOKEN not in response.text
    assert WRONG_TOKEN not in caplog.text


def test_sign_in_without_a_configured_token_starts_no_session(client, no_seed_token):
    response = client.post("/admin/login", json={"token": "anything"})

    assert response.status_code == 204
    assert set_cookies(response) == []


# --- The session ------------------------------------------------------------------------


def test_session_interface(session):
    assert session.COOKIE_NAME == "admin_session"
    assert session.SESSION_SECONDS == 8 * 60 * 60


def test_session_lasts_less_than_8_hours(session):
    issued_at = 1_800_000_000.0
    value = session.issue(ADMIN_TOKEN, issued_at)

    assert session.is_valid(value, ADMIN_TOKEN, issued_at)
    assert session.is_valid(value, ADMIN_TOKEN, issued_at + session.SESSION_SECONDS - 1)
    assert not session.is_valid(value, ADMIN_TOKEN, issued_at + session.SESSION_SECONDS)
    assert not session.is_valid(value, ADMIN_TOKEN, issued_at + session.SESSION_SECONDS + 1)
    assert not session.is_valid(value, ADMIN_TOKEN, issued_at - 3600)  # issued in the future


def test_session_is_bound_to_the_token_and_never_contains_it(session):
    value = session.issue(ADMIN_TOKEN, 1_800_000_000.0)

    assert ADMIN_TOKEN not in value
    assert not session.is_valid(value, "a-rotated-token", 1_800_000_060.0)


@pytest.mark.parametrize("value", [None, "", "garbage", "v1.abc.def", "v1.1800000000."])
def test_malformed_session_values_are_not_valid(session, value):
    assert not session.is_valid(value, ADMIN_TOKEN, 1_800_000_060.0)


def test_altered_session_is_not_valid(session):
    value = session.issue(ADMIN_TOKEN, 1_800_000_000.0)
    last = value[-1]
    altered = value[:-1] + ("0" if last != "0" else "1")

    assert not session.is_valid(altered, ADMIN_TOKEN, 1_800_000_060.0)


@pytest.mark.parametrize("make_cookie", [
    lambda s: cookie(s, age_seconds=8 * 60 * 60 + 1),  # expired
    lambda s: cookie(s, token="the-previous-token"),  # issued before SEED_TOKEN was changed
    lambda s: cookie(s)[:-1] + ("0" if cookie(s)[-1] != "0" else "1"),  # altered
], ids=["expired", "token-rotated", "altered"])
def test_an_ended_or_altered_session_counts_as_none(client, seed_token, session, make_cookie):
    response = client.get("/admin", headers=with_session(make_cookie(session)), follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/admin/login"


# --- Signing out -------------------------------------------------------------------------


def test_sign_out_ends_the_session(client, seed_token):
    client.post("/admin/login", json={"token": ADMIN_TOKEN})
    assert client.get("/admin", follow_redirects=False).status_code == 200

    response = client.post("/admin/logout")

    assert response.status_code == 204
    header = session_cookie_header(response)
    parts = attributes(header)
    assert "max-age=0" in parts or any(p.startswith("expires=thu, 01 jan 1970") for p in parts)
    client.cookies.clear()
    assert client.get("/admin", follow_redirects=False).headers["location"] == "/admin/login"


def test_sign_out_without_a_session(client, seed_token):
    assert client.post("/admin/logout").status_code == 204


# --- The admin page behind the session -----------------------------------------------------


def test_admin_page_redirects_without_a_session(client, seed_token):
    response = client.get("/admin", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/admin/login"
    assert "no-store" in response.headers.get("cache-control", "")
    assert "Knowledge Base Editor" not in response.text


def test_admin_page_with_a_session(client, seed_token, session):
    response = client.get("/admin", headers=with_session(cookie(session)), follow_redirects=False)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "no-store" in response.headers.get("cache-control", "")
    assert "<title>Knowledge Base Editor</title>" in response.text


def test_admin_page_is_open_without_a_configured_token(client, no_seed_token):
    response = client.get("/admin", follow_redirects=False)

    assert response.status_code == 200
    assert "<title>Knowledge Base Editor</title>" in response.text
    assert "no-store" in response.headers.get("cache-control", "")


def test_admin_page_has_the_editor_sign_out_and_an_inline_sign_in(client, no_seed_token):
    html = client.get("/admin").text
    page = Page(html)

    for text in ("Documents", "Settings"):
        assert page.button(text) is not None, f"missing the {text} tab"
    assert "Save" in html and "/seed" in html and "/documents" in html
    assert page.find("a", href="/chat")
    assert page.button("Sign out") is not None
    assert "/admin/logout" in html
    # After a 401 from /seed the page signs in again without leaving: a token form posting to /admin/login.
    assert "/admin/login" in html
    token_input = page.labeled_input("Admin token")
    assert token_input is not None and token_input["attrs"].get("type") == "password"


def assert_keeps_no_token(html: str) -> None:
    for storage in ("sessionStorage", "localStorage", "document.cookie"):
        assert storage not in html
    assert "/admin/verify" not in html


def test_sign_in_page_keeps_no_token_in_browser_storage(client, seed_token):
    response = client.get("/admin/login", follow_redirects=False)

    assert response.status_code == 200
    assert_keeps_no_token(response.text)


def test_admin_page_keeps_no_token_in_browser_storage(client, no_seed_token):
    response = client.get("/admin", follow_redirects=False)

    assert response.status_code == 200
    assert_keeps_no_token(response.text)


def test_token_check_endpoint_is_removed(client, seed_token):
    response = client.get("/admin/verify", headers={"Authorization": f"Bearer {ADMIN_TOKEN}"})

    assert response.status_code == 404


# --- /seed with the bearer token or a session ---------------------------------------------


def test_seed_without_token_or_session_is_refused(client, seed_token, mock_seed):
    assert client.post("/seed", headers={"Origin": f"http://{HOST}"}).status_code == 401
    mock_seed.assert_not_awaited()


def test_seed_with_a_wrong_bearer_token_is_refused(client, seed_token, mock_seed):
    response = client.post("/seed", headers={"Authorization": f"Bearer {WRONG_TOKEN}"})

    assert response.status_code == 401
    mock_seed.assert_not_awaited()


def test_seed_with_the_bearer_token_still_works(client, seed_token, mock_seed):
    response = client.post("/seed", headers={"Authorization": f"Bearer {ADMIN_TOKEN}"})

    assert response.status_code == 200
    assert response.json() == {"inserted": 4}


@pytest.mark.parametrize("origin", [f"http://{HOST}", f"https://{HOST}"], ids=["http", "https-behind-proxy"])
def test_seed_from_the_signed_in_admin_page(client, seed_token, session, mock_seed, origin):
    response = client.post("/seed", headers=with_session(cookie(session), Origin=origin))

    assert response.status_code == 200
    assert response.json() == {"inserted": 4}
    mock_seed.assert_awaited_once()


@pytest.mark.parametrize("extra", [{}, {"Origin": "https://evil.example"}, {"Origin": "null"}],
                         ids=["no-origin", "other-site", "null-origin"])
def test_seed_with_a_session_from_another_site_is_refused(client, seed_token, session, mock_seed, extra):
    response = client.post("/seed", headers=with_session(cookie(session), **extra))

    assert response.status_code == 401
    mock_seed.assert_not_awaited()


@pytest.mark.parametrize("make_cookie", [
    lambda s: cookie(s, age_seconds=8 * 60 * 60 + 1),
    lambda s: cookie(s, token="the-previous-token"),
], ids=["expired", "token-rotated"])
def test_seed_with_an_ended_session_is_refused(client, seed_token, session, mock_seed, make_cookie):
    response = client.post("/seed", headers=with_session(make_cookie(session), Origin=f"http://{HOST}"))

    assert response.status_code == 401
    mock_seed.assert_not_awaited()
