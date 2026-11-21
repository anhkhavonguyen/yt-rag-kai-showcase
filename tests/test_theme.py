"""The shared light theme of every page (spec ui-theme of the change modern-light-redesign).

Checks what can be read from the served files: the shared stylesheet, its color tokens
and components, WCAG contrast between the tokens, that every page uses the stylesheet
and defines no colors of its own, the light color scheme, a keyboard focus style,
reduced motion, no external resources, and the chat page's content (spec
profile-assistant): the hero, skills and certifications, sample questions and how
answers are rendered. How the pages look at phone width and with the keyboard is
checked by hand in a browser.

static/theme.css must define these tokens in :root as #rrggbb values:
    --bg --surface --surface-raised --text --text-muted --accent --accent-strong
    --on-accent --border --border-strong --danger --success --focus --tag-bg --chip-bg
    --hero-bg --footer-bg --on-band --on-band-muted --focus-on-band
"""

import re
from html.parser import HTMLParser

import pytest

import app.main
from app.data.default_documents import DEFAULT_DOCUMENTS

TOKENS = ["bg", "surface", "surface-raised", "text", "text-muted", "accent", "accent-strong",
          "on-accent", "border", "border-strong", "danger", "success", "focus", "tag-bg", "chip-bg",
          "hero-bg", "footer-bg", "on-band", "on-band-muted", "focus-on-band"]

# (foreground, background, minimum ratio): WCAG AA, 4.5:1 for text and 3:1 for controls and focus.
CONTRAST_PAIRS = [
    # Normal and muted text
    ("text", "bg", 4.5), ("text", "surface", 4.5), ("text", "surface-raised", 4.5),
    ("text-muted", "bg", 4.5), ("text-muted", "surface", 4.5), ("text-muted", "surface-raised", 4.5),
    # Error and success messages
    ("danger", "bg", 4.5), ("danger", "surface", 4.5),
    ("success", "bg", 4.5), ("success", "surface", 4.5),
    # Buttons: text on the button (the button against the page needs 3:1, links below need more)
    ("on-accent", "accent", 4.5), ("on-accent", "accent-strong", 4.5),
    # Links, source titles and sample questions
    ("accent", "bg", 4.5), ("accent", "surface", 4.5), ("accent", "surface-raised", 4.5),
    ("accent", "chip-bg", 4.5),
    # Skill tags
    ("text", "tag-bg", 4.5),
    # Input borders
    ("border-strong", "bg", 3.0), ("border-strong", "surface", 3.0), ("border-strong", "surface-raised", 3.0),
    # The focus indicator on light surfaces
    ("focus", "bg", 3.0), ("focus", "surface", 3.0), ("focus", "surface-raised", 3.0), ("focus", "chip-bg", 3.0),
    # The dark hero and footer bands: text, buttons and focus
    ("on-band", "hero-bg", 4.5), ("on-band", "footer-bg", 4.5),
    ("on-band-muted", "hero-bg", 4.5), ("on-band-muted", "footer-bg", 4.5),
    ("hero-bg", "on-band", 4.5),
    ("focus-on-band", "hero-bg", 3.0), ("focus-on-band", "footer-bg", 3.0),
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


def test_stylesheet_is_light_and_has_a_keyboard_focus_style(theme_css):
    assert re.search(r"color-scheme\s*:\s*light", theme_css)
    assert not re.search(r"color-scheme\s*:\s*dark", theme_css)
    assert luminance(tokens(theme_css)["bg"]) > luminance(tokens(theme_css)["text"])  # dark text on light
    focus_rules = re.findall(r":focus-visible[^{]*\{([^}]*)\}", theme_css)
    assert any("outline" in rule and "var(--focus)" in rule for rule in focus_rules), \
        "theme.css needs a :focus-visible rule with an outline in var(--focus)"


def test_stylesheet_follows_no_system_preference_and_loads_nothing_external(theme_css):
    assert "prefers-color-scheme" not in theme_css  # always the one light palette
    assert not re.search(r"url\(\s*['\"]?https?:", theme_css)
    assert not re.search(r"@import", theme_css)


def test_stylesheet_sets_the_font_and_no_page_loads_a_font_file(theme_css, pages):
    body = re.search(r"(?:^|[}\s])body\s*\{([^}]*)\}", theme_css)

    assert body and "font-family" in body.group(1), "theme.css needs a body rule with a font-family"
    assert "@font-face" not in theme_css
    for path, html in pages.items():
        assert "@font-face" not in html, f"{path} declares a font file"


# Shared components (spec: pages share one set of components)
SHARED_COMPONENTS = [".button-primary", ".button-secondary", ".card", ".chip", ".tag", ".field", ".top-bar"]


@pytest.mark.parametrize("selector", SHARED_COMPONENTS)
def test_stylesheet_defines_the_shared_components(theme_css, selector):
    assert re.search(re.escape(selector) + r"\s*[,{]", theme_css), f"theme.css has no {selector} rule"


def test_focus_inside_the_dark_bands_uses_the_band_focus_color(theme_css):
    band_rules = re.findall(r"\.band\s+:focus-visible\s*\{([^}]*)\}", theme_css)

    assert any("var(--focus-on-band)" in rule for rule in band_rules), \
        "theme.css needs a .band :focus-visible rule in var(--focus-on-band)"


# Motion (spec: motion is calm and can be turned off)
DURATION = re.compile(r"(\d*\.?\d+)(ms|s)\b")


def test_stylesheet_turns_off_motion_when_asked(theme_css):
    block = re.search(r"@media\s*\(\s*prefers-reduced-motion\s*:\s*reduce\s*\)\s*\{(.*?)\n\}", theme_css, re.S)

    assert block, "theme.css needs a @media (prefers-reduced-motion: reduce) block"
    assert "animation-duration" in block.group(1) and "transition-duration" in block.group(1)


def test_animations_and_transitions_last_at_most_300ms(theme_css, pages):
    sources = {"theme.css": theme_css}
    for path, html in pages.items():
        page = Resources(html)
        sources[path] = "\n".join(page.style_blocks + page.style_attributes)

    for name, css in sources.items():
        for prop, value in re.findall(r"\b(transition|animation)(?:-duration)?\s*:\s*([^;}]+)", css):
            if "typing" in value:
                continue  # the typing indicator's dots may keep bouncing while an answer is pending
            for number, unit in DURATION.findall(value):
                milliseconds = float(number) * (1000 if unit == "s" else 1)
                assert milliseconds <= 300, f"{name}: {prop}: {value.strip()} lasts over 300 ms"


# --- The pages ----------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/chat", "/admin", "/admin/login"])
def test_page_uses_the_shared_stylesheet_and_no_colors_of_its_own(pages, path):
    page = Resources(pages[path])

    assert "/static/theme.css" in page.stylesheets
    for css in page.style_blocks + page.style_attributes:
        assert not HEX_COLOR.search(css), f"{path} defines its own color: {HEX_COLOR.search(css).group()}"


@pytest.mark.parametrize("path", ["/chat", "/admin", "/admin/login"])
def test_page_declares_the_light_color_scheme_and_has_no_theme_toggle(pages, path):
    page = Resources(pages[path])

    assert {"name": "color-scheme", "content": "light"} in [
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


def element_html(html: str, element_id: str) -> str:
    """The element with id `element_id`, from its start tag to its matching end tag."""
    start = re.search(rf'<(\w+)[^>]*\bid="{re.escape(element_id)}"', html)
    assert start, f'no element with id="{element_id}"'
    tag, offset = start.group(1), start.start()
    depth = 0
    for match in re.finditer(rf"<(/?){tag}\b[^>]*>", html[offset:]):
        depth += -1 if match.group(1) else 1
        if depth == 0:
            return html[offset:offset + match.end()]
    raise AssertionError(f'the element with id="{element_id}" is not closed')


def region(html: str, element_id: str) -> Elements:
    return Elements(element_html(html, element_id))


def top_bar_html(html: str) -> str:
    match = re.search(r'<header class="top-bar".*?</header>', html, re.S)
    assert match, "the page has no top bar"
    return match.group()


def test_chat_page_keeps_its_content(pages, chat):
    html = pages["/chat"]

    assert "<title>Meet Kai</title>" in html
    assert re.search(r"<h1[^>]*>\s*Meet Kai\s*</h1>", html)
    assert "Ask about Kha Vo's experience, skills and work" in visible_text(chat)
    assert 'id="status"' in html
    assert re.search(r"<input[^>]*id=\"messageInput\"", html)
    assert 'placeholder="Ask a question about Kai..."' in html
    send = next(b for b in chat.buttons if b.get("id") == "sendBtn")
    assert send["text"].strip() == "Send"  # its accessible name, also when only the icon shows
    assert re.search(r'id="sendBtn"[^>]*>\s*<svg[^>]*aria-hidden="true"', html), "the Send icon is decorative"
    assert "/answer" in html and "/healthz" in html


def test_chat_page_has_no_admin_entry(pages):
    assert "/admin" not in pages["/chat"]


def test_chat_page_shows_no_store_wording(chat):
    text = visible_text(chat).lower()

    for wording in ("customer support", "returns", "shipping", "sizing", "policies"):
        assert wording not in text, f"/chat shows {wording!r}"


# Profile (spec: the chat page shows Kai's profile, skills and certifications)


def test_hero_shows_who_kai_is(pages):
    about = region(pages["/chat"], "about")
    text = visible_text(about)

    for expected in ("Kha Vo", "Known as Kai", "Team Lead | Enterprise Software & AI Solutions",
                     "Ho Chi Minh City, Vietnam", "12+ years", "Team Lead, Orient Software"):
        assert expected in text, f"the hero lacks {expected!r}"
    assert LINKEDIN in [link.get("href") for link in about.links]
    assert re.search(r"<h1[^>]*>\s*Meet Kai\s*</h1>", element_html(pages["/chat"], "about"))


def test_skills_section_shows_both_groups_as_tags(pages):
    skills_html = element_html(pages["/chat"], "skills")
    text = visible_text(Elements(skills_html))

    assert re.search(r"<h2[^>]*>\s*Skills\s*</h2>", skills_html)
    for group in ("Enterprise &amp; cloud", "AI"):
        assert re.search(rf"<h3[^>]*>\s*{re.escape(group)}\s*</h3>", skills_html), f"no {group!r} group"
    assert skills_html.count('<ul class="tags">') == 2
    for tag in ("C#", ".NET", "Microsoft Azure", "RAG", "AI agents", "Claude Code"):
        assert tag in text, f"the Skills section lacks {tag!r}"


def test_certifications_section_shows_each_certification_with_its_issuer(pages):
    certifications_html = element_html(pages["/chat"], "certifications")
    text = visible_text(Elements(certifications_html))

    assert re.search(r"<h2[^>]*>\s*Certifications\s*</h2>", certifications_html)
    assert certifications_html.count('class="card cert-card"') == len(CERTIFICATIONS)
    for expected in (*CERTIFICATIONS, "Anthropic", "Amazon Web Services", "Oracle", "Programming in C# · Microsoft"):
        assert expected in text, f"the Certifications section lacks {expected!r}"


def test_certifications_link_to_their_public_verification_pages(pages):
    verify_links = {
        link.get("href") for link in region(pages["/chat"], "certifications").links if "Verify" in link["text"]
    }

    assert verify_links == {
        "https://verify.skilljar.com/c/8ef23mi7ch5g",  # Claude Code in Action, Anthropic
        "https://www.credly.com/badges/666fe70b-04f6-4311-a8e3-d2583b76df77",  # AWS Educate ML Foundations
    }


def test_every_certification_on_the_page_is_in_the_education_document(pages):
    education = next(d["text"] for d in DEFAULT_DOCUMENTS if d["chunk_id"] == "kai_education_certifications_v1")
    names = re.findall(r'class="cert-name">([^<]+)<', pages["/chat"])

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


def test_skills_and_certifications_are_shown_without_a_toggle(chat, pages):
    labels = [button["text"].strip() for button in chat.buttons]

    assert "Show more" not in labels and "Show less" not in labels
    assert "profile-more" not in pages["/chat"] and "aria-expanded" not in pages["/chat"]


# Top bar and footer (specs: every page starts with a top bar; the chat page ends with a footer)


def test_chat_top_bar_has_the_wordmark_section_links_and_linkedin(pages, theme_css):
    html = pages["/chat"]
    bar = Elements(top_bar_html(html))
    hrefs = [link.get("href") for link in bar.links]

    assert any(link["text"].strip() == "Meet Kai" and "wordmark" in link.get("class", "") for link in bar.links)
    for anchor in ("#chat", "#skills", "#certifications"):
        assert anchor in hrefs, f"the top bar doesn't link to {anchor}"
        assert f'id="{anchor[1:]}"' in html, f"{anchor} leads nowhere"
    assert LINKEDIN in hrefs
    assert not any("/admin" in (href or "") for href in hrefs)
    assert re.search(r"\.top-bar\s*\{[^}]*position\s*:\s*sticky", theme_css), "the top bar stays visible"


def test_chat_page_ends_with_a_footer_that_credits_the_profile(pages):
    html = pages["/chat"]
    match = re.search(r"<footer\b.*?</footer>", html, re.S)

    assert match and match.start() > html.index("</main>"), "the footer follows the main content"
    footer = Elements(match.group())
    assert "Kai's public LinkedIn profile" in visible_text(footer)
    assert any(link.get("href") == LINKEDIN and link.get("target") == "_blank" for link in footer.links)
    assert "/admin" not in match.group()


# Layout (spec: the chat page layout fits the screen)


def test_hero_puts_the_introduction_and_chat_side_by_side_from_1024px(pages):
    html = pages["/chat"]
    wide = re.search(r"@media\s*\(\s*min-width:\s*1024px\s*\)\s*\{(.*?)\n        \}", html, re.S)

    assert wide, "no @media (min-width: 1024px) block"
    assert re.search(r"\.hero-grid\s*\{[^}]*grid-template-columns", wide.group(1))
    assert html.index('id="about"') < html.index('id="chat"'), "the introduction comes before the chat card"
    assert html.index('id="chat"') < html.index('id="skills"') < html.index('id="certifications"')


# Jumping to the chat (spec: visitors can jump straight to the chat)


def test_skip_link_is_the_first_focusable_element_and_leads_to_the_chat(pages, chat):
    html = pages["/chat"]
    first = chat.links[0]

    assert first.get("href") == "#chat" and first["text"].strip() == "Skip to chat"
    assert "skip-link" in first.get("class", "")
    body = html[html.index("<body"):]
    assert body.index('class="skip-link"') < min(body.index(tag) for tag in ("<button", "<input"))


def test_hero_call_to_action_and_skip_link_move_focus_to_the_input(pages, chat):
    about = region(pages["/chat"], "about")

    assert any(link.get("href") == "#chat" and link["text"].strip().startswith("Ask a question") for link in about.links)
    assert "querySelectorAll('a[href=\"#chat\"]')" in chat.script
    focus_chat = re.search(r"function focusChat\(\)\s*\{(.*?)\n        \}", chat.script, re.S)
    assert focus_chat, "focusChat() not found"
    assert "scrollIntoView" in focus_chat.group(1) and "messageInput.focus" in focus_chat.group(1)


def test_input_gets_focus_on_load_only_in_the_wide_layout(chat):
    init = re.search(r"async function init\(\)\s*\{(.*?)\n        \}", chat.script, re.S)

    assert "matchMedia('(min-width: 1024px)')" in chat.script
    assert init and "wideLayout.matches" in init.group(1) and "messageInput.focus" in init.group(1)


# Messages (spec: messages say who wrote them)


def test_messages_are_a_log_that_screen_readers_announce(pages):
    assert re.search(r'<div[^>]*id="messages"[^>]*role="log"', pages["/chat"])


def test_each_message_says_who_wrote_it_and_the_assistant_is_not_kai(pages, chat):
    assert "'You: '" in chat.script and "\"Kai's assistant: \"" in chat.script
    assert "assistantAvatarTemplate.content" in chat.script and "cloneNode(true)" in chat.script
    avatar = element_html(pages["/chat"], "assistant-avatar")
    assert "<svg" in avatar and "KV" not in avatar
    assert "Kai's assistant: " in visible_text(chat)  # the welcome message is labeled too


# No emoji in the page's own interface text (spec: icons are decorative or named)
EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿⬀-⯿️]")


@pytest.mark.parametrize("path", ["/chat", "/admin", "/admin/login"])
def test_page_has_no_emoji(pages, path):
    found = EMOJI.search(pages[path])

    assert not found, f"{path} contains the emoji {found.group()!r}"


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

    assert "`Saved ${data.inserted} chunks, removed ${data.removed} old ones`" in html
    for label in ("'Saving…'", "'Saved'", "'Save failed'"):
        assert f"saveText.textContent = {label}" in html, f"the Save button never reads {label}"


# --- Shared across the three pages ----------------------------------------------------------


@pytest.mark.parametrize("path", ["/admin", "/admin/login"])
def test_admin_pages_start_with_a_top_bar_labeled_admin_that_links_back_to_chat(pages, path):
    html = pages[path]
    bar_html = top_bar_html(html)
    bar = Elements(bar_html)

    assert html.index('<header class="top-bar"') < html.index("<main"), "the top bar comes first"
    assert re.search(r'class="wordmark"[^>]*>\s*Meet Kai\s*<', bar_html)
    assert re.search(r'class="badge"[^>]*>\s*Admin\s*<', bar_html)
    assert any(link.get("href") == "/chat" and "Back to chat" in link["text"] for link in bar.links)
    if path == "/admin":
        assert any(button.get("id") == "signOutBtn" and button["text"].strip() == "Sign out" for button in bar.buttons)


@pytest.mark.parametrize("path, button_id", [("/chat", "sendBtn"), ("/admin/login", "signInBtn"), ("/admin", "saveBtn")])
def test_primary_actions_use_the_shared_primary_button(pages, path, button_id):
    button = next(b for b in Elements(pages[path]).buttons if b.get("id") == button_id)

    assert "button-primary" in button.get("class", "").split(), f"{path} #{button_id} isn't a primary button"


# --- The sign-in page links back to the chat page ---------------------------------------------


def test_sign_in_page_links_back_to_chat(pages):
    links = Elements(pages["/admin/login"]).links

    assert any(link.get("href") == "/chat" and "Back to chat" in link["text"] for link in links)
    assert "Customer Support" not in pages["/admin/login"]
