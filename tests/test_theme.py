"""The shared dark theme of every page (spec ui-theme of the change dark-theme-admin-sign-in-via-agents).

Checks what can be read from the served files: the shared stylesheet and its color
tokens, WCAG contrast between them, that every page uses the stylesheet and defines
no colors of its own, the dark color scheme, a keyboard focus style, no external
resources, and that the Customer Support page keeps its content. How the pages look
at phone width and with the keyboard is checked by hand in a browser.

static/theme.css must define these tokens in :root as #rrggbb values:
    --bg --surface --surface-raised --text --text-muted --accent --on-accent
    --border --danger --success --focus
"""

import re
from html.parser import HTMLParser

import pytest

import app.main

TOKENS = ["bg", "surface", "surface-raised", "text", "text-muted", "accent", "on-accent",
          "border", "danger", "success", "focus"]

# (foreground, background, minimum ratio): WCAG AA, 4.5:1 for text and 3:1 for controls and focus.
CONTRAST_PAIRS = [
    ("text", "bg", 4.5), ("text", "surface", 4.5), ("text", "surface-raised", 4.5),
    ("text-muted", "bg", 4.5), ("text-muted", "surface", 4.5), ("text-muted", "surface-raised", 4.5),
    ("danger", "bg", 4.5), ("danger", "surface", 4.5),
    ("success", "bg", 4.5), ("success", "surface", 4.5),
    ("on-accent", "accent", 4.5),
    ("accent", "bg", 3.0), ("focus", "bg", 3.0), ("focus", "surface", 3.0),
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


# --- The Customer Support page keeps its content -----------------------------------------------


def test_customer_support_page_keeps_its_content(pages):
    html = pages["/chat"]

    assert "<title>Customer Support</title>" in html
    assert re.search(r"<h1[^>]*>\s*Customer Support\s*</h1>", html)
    assert "Chat with our AI assistant for help with orders, returns, and policies" in html
    assert "Welcome to the AI Assistant!" in html
    assert 'id="status"' in html
    assert re.search(r"<input[^>]*id=\"messageInput\"", html)
    assert re.search(r"<button[^>]*>\s*Send\s*</button>", html)
    assert "/answer" in html and "/healthz" in html


def test_customer_support_page_has_no_admin_entry(pages):
    assert "/admin" not in pages["/chat"]
