"""The shared dark theme of every page (spec ui-theme of the change dark-theme-admin-sign-in-via-agents).

Checks what can be read from the served files: the shared stylesheet and its color
tokens, WCAG contrast between them, that every page uses the stylesheet and defines
no colors of its own, the dark color scheme, a keyboard focus style, no external
resources, and the chat page's content (spec profile-assistant of the change
profile-assistant-about-kai): the profile panel, sample questions and how answers are
rendered. How the pages look at phone width and with the keyboard is checked by hand in
a browser.

static/theme.css must define these tokens in :root as #rrggbb values:
    --bg --surface --surface-raised --text --text-muted --accent --on-accent
    --border --danger --success --focus --tag-bg --chip-bg
"""

import re
from html.parser import HTMLParser

import pytest

import app.main
from app.data.default_documents import DEFAULT_DOCUMENTS

TOKENS = ["bg", "surface", "surface-raised", "text", "text-muted", "accent", "on-accent",
          "border", "danger", "success", "focus", "tag-bg", "chip-bg"]

# (foreground, background, minimum ratio): WCAG AA, 4.5:1 for text and 3:1 for controls and focus.
CONTRAST_PAIRS = [
    ("text", "bg", 4.5), ("text", "surface", 4.5), ("text", "surface-raised", 4.5),
    ("text-muted", "bg", 4.5), ("text-muted", "surface", 4.5), ("text-muted", "surface-raised", 4.5),
    ("danger", "bg", 4.5), ("danger", "surface", 4.5),
    ("success", "bg", 4.5), ("success", "surface", 4.5),
    ("on-accent", "accent", 4.5),
    ("accent", "bg", 3.0), ("focus", "bg", 3.0), ("focus", "surface", 3.0),
    # The chat page's profile panel, sample questions and answer sources
    ("text", "tag-bg", 4.5), ("accent", "chip-bg", 4.5),
    ("accent", "surface", 4.5), ("accent", "surface-raised", 4.5),
    ("focus", "surface-raised", 3.0), ("focus", "chip-bg", 3.0),
]

HEX_COLOR = re.compile(r"#[0-9a-fA-F]{3,8}\b")


@pytest.fixture(autouse=True)
def no_seed_token(monkeypatch):
    """No token configured, so /admin opens directly. The sign-in page needs one: see `pages`."""
    monkeypatch.setattr(app.main.settings, "seed_token", None)


@pytest.fixture
def theme_css(client) -> str:
    response = client.get("/static/theme.css")
    assert response.status_code == 200
    return response.text


@pytest.fixture
def pages(client, monkeypatch) -> dict[str, str]:
    """The HTML of /chat, /admin (no token configured) and /admin/login (token configured, signed out)."""
    html = {}
    for path in ("/chat", "/admin"):
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 200, path
        html[path] = response.text
    monkeypatch.setattr(app.main.settings, "seed_token", "theme-test-token")
    response = client.get("/admin/login", follow_redirects=False)
    assert response.status_code == 200
    html["/admin/login"] = response.text
    return html


def tokens(css: str) -> dict[str, str]:
    """The custom properties defined in :root blocks, such as {"bg": "#0f1117"}."""
    found = {}
    for block in re.findall(r":root\s*\{([^}]*)\}", css):
        for name, value in re.findall(r"--([\w-]+)\s*:\s*([^;]+);", block):
            found[name] = value.strip()
    return found


def luminance(hex_color: str) -> float:
    value = hex_color.lstrip("#")
    channels = [int(value[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(foreground: str, background: str) -> float:
    lighter, darker = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


class Resources(HTMLParser):
    """Collects a page's stylesheet links, script and media sources, inline styles and meta tags."""

    def __init__(self, html: str):
        super().__init__()
        self.stylesheets: list[str] = []
        self.sources: list[str] = []
        self.style_attributes: list[str] = []
        self.style_blocks: list[str] = []
        self.metas: list[dict] = []
        self._in_style = False
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "link" and "stylesheet" in (attrs.get("rel") or "").lower():
            self.stylesheets.append(attrs.get("href") or "")
        if attrs.get("src"):
            self.sources.append(attrs["src"])
        if attrs.get("style"):
            self.style_attributes.append(attrs["style"])
        if tag == "meta":
            self.metas.append(attrs)
        self._in_style = tag == "style"

    def handle_endtag(self, tag):
        if tag == "style":
            self._in_style = False

    def handle_data(self, data):
        if self._in_style:
            self.style_blocks.append(data)


# --- The stylesheet ------------------------------------------------------------------------


def test_stylesheet_is_served_as_css(client):
    response = client.get("/static/theme.css")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/css")


def test_stylesheet_defines_every_token_as_a_hex_color(theme_css):
    defined = tokens(theme_css)

    for name in TOKENS:
        assert name in defined, f"--{name} is not defined in :root"
        assert re.fullmatch(r"#[0-9a-fA-F]{6}", defined[name]), f"--{name} must be #rrggbb, not {defined[name]!r}"


@pytest.mark.parametrize("foreground, background, minimum", CONTRAST_PAIRS,
                         ids=[f"{f}-on-{b}" for f, b, _ in CONTRAST_PAIRS])
def test_contrast(theme_css, foreground, background, minimum):
    defined = tokens(theme_css)

    ratio = contrast(defined[foreground], defined[background])

    assert ratio >= minimum, f"--{foreground} on --{background} is {ratio:.2f}:1, needs {minimum}:1"


def test_stylesheet_is_dark_and_has_a_keyboard_focus_style(theme_css):
    assert re.search(r"color-scheme\s*:\s*dark", theme_css)
    assert luminance(tokens(theme_css)["bg"]) < luminance(tokens(theme_css)["text"])  # light text on dark
    focus_rules = re.findall(r":focus-visible[^{]*\{([^}]*)\}", theme_css)
    assert any("outline" in rule and "var(--focus)" in rule for rule in focus_rules), \
        "theme.css needs a :focus-visible rule with an outline in var(--focus)"


def test_stylesheet_follows_no_system_preference_and_loads_nothing_external(theme_css):
    assert "prefers-color-scheme" not in theme_css  # always dark
    assert not re.search(r"url\(\s*['\"]?https?:", theme_css)
    assert not re.search(r"@import", theme_css)


# --- The pages ----------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/chat", "/admin", "/admin/login"])
def test_page_uses_the_shared_stylesheet_and_no_colors_of_its_own(pages, path):
    page = Resources(pages[path])

    assert "/static/theme.css" in page.stylesheets
    for css in page.style_blocks + page.style_attributes:
        assert not HEX_COLOR.search(css), f"{path} defines its own color: {HEX_COLOR.search(css).group()}"


@pytest.mark.parametrize("path", ["/chat", "/admin", "/admin/login"])
def test_page_declares_the_dark_color_scheme_and_has_no_theme_toggle(pages, path):
    page = Resources(pages[path])

    assert {"name": "color-scheme", "content": "dark"} in [
        {"name": m.get("name"), "content": m.get("content")} for m in page.metas
    ]
    lowered = pages[path].lower()
    for toggle in ("theme-toggle", "theme toggle", "toggle theme", "light mode", "dark mode", "prefers-color-scheme"):
        assert toggle not in lowered


@pytest.mark.parametrize("path", ["/chat", "/admin", "/admin/login"])
def test_page_loads_nothing_from_other_sites(pages, path):
    page = Resources(pages[path])

    for url in page.stylesheets + page.sources:
        assert not re.match(r"(https?:)?//", url), f"{path} loads {url}"
    for css in page.style_blocks + page.style_attributes:
        assert not re.search(r"url\(\s*['\"]?(https?:)?//", css)
        assert "@import" not in css


# --- The chat page: Meet Kai -------------------------------------------------------------------


class Elements(HTMLParser):
    """A page's links, buttons, visible text (without <style> and <script>) and script source."""

    def __init__(self, html: str):
        super().__init__()
        self.links: list[dict] = []
        self.buttons: list[dict] = []
        self.visible: list[str] = []
        self.script = ""
        self._skip = None  # "style" or "script" while inside one
        self._open: list[dict] = []  # links and buttons whose text is being collected
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag in ("style", "script"):
            self._skip = tag
        elif tag in ("a", "button"):
            element = {**dict(attrs), "text": ""}
            (self.links if tag == "a" else self.buttons).append(element)
            self._open.append(element)

    def handle_endtag(self, tag):
        if tag == self._skip:
            self._skip = None
        elif tag in ("a", "button") and self._open:
            self._open.pop()

    def handle_data(self, data):
        if self._skip == "script":
            self.script += data
        elif self._skip is None:
            self.visible.append(data)
            for element in self._open:
                element["text"] += data


CERTIFICATIONS = [
    "Claude Code in Action",
    "AWS Educate Machine Learning Foundations",
    "Oracle Cloud Infrastructure 2025 Certified AI Foundations Associate",
    "Microsoft Certified Professional",
]
SAMPLE_QUESTIONS = [
    "Who is Kai?",
    "What can Kai do?",
    "What is Kai working on now?",
    "What AI experience does Kai have?",
    "Which certifications does Kai have?",
]
LINKEDIN = "https://www.linkedin.com/in/khavo2907/"


@pytest.fixture
def chat(pages) -> Elements:
    return Elements(pages["/chat"])


def visible_text(page: Elements) -> str:
    return " ".join(" ".join(page.visible).split())


def profile_panel(html: str) -> Elements:
    return Elements(html[html.index("<aside"):html.index("</aside>")])


def test_chat_page_keeps_its_content(pages, chat):
    html = pages["/chat"]

    assert "<title>Meet Kai</title>" in html
    assert re.search(r"<h1[^>]*>\s*Meet Kai\s*</h1>", html)
    assert "Ask about Kha Vo's experience, skills and work" in visible_text(chat)
    assert 'id="status"' in html
    assert re.search(r"<input[^>]*id=\"messageInput\"", html)
    assert 'placeholder="Ask a question about Kai..."' in html
    assert re.search(r"<button[^>]*>\s*Send\s*</button>", html)
    assert "/answer" in html and "/healthz" in html


def test_chat_page_has_no_admin_entry(pages):
    assert "/admin" not in pages["/chat"]


def test_chat_page_shows_no_store_wording(chat):
    text = visible_text(chat).lower()

    for wording in ("customer support", "returns", "shipping", "sizing", "policies"):
        assert wording not in text, f"/chat shows {wording!r}"


# Profile panel (spec: the chat page shows Kai's profile, skills and certifications)


def test_profile_panel_shows_kai_skills_and_certifications(pages):
    panel = profile_panel(pages["/chat"])
    text = visible_text(panel)

    for expected in ("Kha Vo", "Known as Kai", "Team Lead | Enterprise Software & AI Solutions",
                     "Ho Chi Minh City, Vietnam", "12+ years", "Orient Software",
                     "Enterprise & cloud", "AI", "Programming in C#", *CERTIFICATIONS):
        assert expected in text, f"profile panel lacks {expected!r}"
    assert LINKEDIN in [link.get("href") for link in panel.links]


def test_certifications_link_to_their_public_verification_pages(pages):
    verify_links = {
        link.get("href") for link in profile_panel(pages["/chat"]).links if "Verify" in link["text"]
    }

    assert verify_links == {
        "https://verify.skilljar.com/c/8ef23mi7ch5g",  # Claude Code in Action, Anthropic
        "https://www.credly.com/badges/666fe70b-04f6-4311-a8e3-d2583b76df77",  # AWS Educate ML Foundations
    }


def test_every_certification_on_the_page_is_in_the_education_document(pages):
    education = next(d["text"] for d in DEFAULT_DOCUMENTS if d["chunk_id"] == "kai_education_certifications_v1")
    names = re.findall(r'<div class="cert-name">([^<]+)</div>', pages["/chat"])

    assert names == CERTIFICATIONS
    for name in names:
        assert name in education, f"{name!r} is on the page but not in kai_education_certifications_v1"


def test_links_to_other_sites_open_in_a_new_tab_without_access_to_the_page(chat):
    external = [link for link in chat.links if re.match(r"https?://", link.get("href") or "")]

    assert external, "expected at least the LinkedIn link"
    for link in external:
        assert link.get("target") == "_blank", link
        assert {"noopener", "noreferrer"} <= set((link.get("rel") or "").split()), link
        assert "(opens in a new tab)" in link["text"], link


def test_no_github_and_no_empty_or_placeholder_links(chat):
    for link in chat.links:
        href = (link.get("href") or "").strip()
        assert href not in ("", "#"), link
        assert "github.com" not in href, link


def test_show_more_button_reports_its_state(chat, pages):
    toggle = next(b for b in chat.buttons if b.get("id") == "profileMoreToggle")

    assert toggle["text"].strip() == "Show more"
    assert toggle.get("type") == "button"
    assert toggle.get("aria-controls") == "profile-more"
    assert toggle.get("aria-expanded") == "false"
    assert 'id="profile-more"' in pages["/chat"]
    assert "setAttribute('aria-expanded'" in chat.script and "Show less" in chat.script


def test_layout_switches_to_two_columns_from_900px(pages):
    assert re.search(r"@media\s*\(\s*min-width:\s*900px\s*\)", pages["/chat"])


# Sample questions (spec: sample questions are asked with one click)


def test_welcome_message_offers_the_sample_questions_as_buttons(chat):
    samples = [b for b in chat.buttons if "sample-question" in (b.get("class") or "").split()]

    assert [b["text"].strip() for b in samples] == SAMPLE_QUESTIONS
    assert all(b.get("type") == "button" for b in samples)
    assert "I answer questions about Kha Vo, known as Kai, using Kai's LinkedIn profile" in visible_text(chat)


def test_sample_questions_are_disabled_while_an_answer_is_pending(chat):
    waiting = re.search(r"function setWaiting\(waiting\)\s*\{(.*?)\n        \}", chat.script, re.S)

    assert waiting, "setWaiting() not found"
    assert "sendBtn.disabled = waiting" in waiting.group(1)
    assert "'.sample-question'" in waiting.group(1) and "button.disabled = waiting" in waiting.group(1)


def test_send_returns_early_while_an_answer_is_pending(chat):
    body = chat.script[chat.script.index("async function sendMessage()"):]

    assert re.match(r"async function sendMessage\(\)\s*\{\s*if \(pending\) return;", body)


# Answers (spec: each answer shows its sources and how it was made; plain text)


def test_answers_are_rendered_as_plain_text(chat):
    assert "innerHTML" not in chat.script
    assert "insertAdjacentHTML" not in chat.script
    assert "textContent" in chat.script


def test_answers_show_numbered_sources_and_how_they_were_made(chat):
    script = chat.script

    assert "createElement('details')" in script and "createElement('summary')" in script
    assert "data.sources" in script
    assert "answer_mode" in script and "latency_ms" in script
    assert "'AI answer'" in script
    assert "'Passages only (AI unavailable)'" in script


# --- The admin page reports what a save changed -----------------------------------------------


def test_admin_save_message_reports_inserted_and_removed(pages):
    html = pages["/admin"]

    assert "✅ Saved ${data.inserted} chunks, removed ${data.removed} old ones" in html


# --- The sign-in page links back to the chat page ---------------------------------------------


def test_sign_in_page_links_back_to_chat(pages):
    links = Elements(pages["/admin/login"]).links

    assert any(link.get("href") == "/chat" and "Back to chat" in link["text"] for link in links)
    assert "Customer Support" not in pages["/admin/login"]
