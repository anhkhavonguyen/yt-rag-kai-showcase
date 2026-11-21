# Proposal

## Why

Meet Kai is the owner's public showcase, but its pages still look like the original support-chat demo: a dark, boxed app window with emoji avatars, a side panel of dense text, and little visual hierarchy. The owner wants a modern, professional look that holds up next to corporate sites such as the DEKRA home page: light, clean, generous whitespace, bold headings, one strong green accent and clear sections.

## What Changes

- **BREAKING (visual)**: the site switches from dark-only to a single **light** palette. The shared stylesheet `static/theme.css` gets a new light token set: white and very light gray surfaces, near-black text, a deep green accent used sparingly, and dark bands for the hero and footer. The pages declare the light color scheme. There is still one palette, no theme toggle and no OS-preference switching.
- New shared design foundations in `theme.css`: a system font stack with a bold type scale, spacing and radius scale, card, button, chip, tag, top-bar and footer components, a strong control border for inputs, a two-tone focus ring that stays visible on light surfaces and on dark bands, and reduced motion when the visitor asks for it.
- **`/chat` is re-laid out as a profile landing page with the chat built in**:
  - a slim sticky top bar with a "Meet Kai" wordmark, in-page links and LinkedIn;
  - a dark green hero band introducing Kai (name, nickname, headline, key facts, calls to action), with the chat card beside it on wide screens and below the intro on narrow ones;
  - "Skills" and "Certifications" sections as cards;
  - a dark footer.
  The side profile panel and its "Show more" toggle are removed: skills and certifications become full sections that every screen size shows.
- The chat card itself is restyled: monogram and icon avatars instead of emoji, cleaner message bubbles, sample questions as chips, a status pill, an input bar with an icon send button, and a visible but calm typing indicator. All chat behavior stays the same: `/healthz`, `/answer`, numbered sources, mode line, plain-text rendering, one question at a time.
- `/admin/login` and `/admin` move to the same light look: top bar, card-based sign-in, document cards, underline tabs, and a sticky save bar. Their content, element IDs and behavior stay as they are.
- `tests/test_theme.py` is updated to check the new palette, contrast pairs, light color scheme and the new `/chat` structure. Tests for the removed "Show more" toggle are dropped.

Out of scope: new content or facts about Kai, photography or other images of Kai, a hero carousel, a dark mode or theme toggle, web fonts loaded from other sites, changes to any API, the CLI chatbot, and the stale values shown on the admin Settings tab.

## Capabilities

### New Capabilities
<!-- None: the visual system belongs to the existing ui-theme capability. -->

### Modified Capabilities
- `ui-theme`: "Every page is dark" is replaced by a single light palette. Contrast rules are extended for links on light surfaces, input borders and the dark hero and footer bands. New requirements cover the shared layout chrome (top bar, footer, sections), reduced motion, and the admin pages keeping their content and behavior. The chat-page content requirement is updated for the new layout.
- `profile-assistant`: "The chat page shows Kai's profile, skills and certifications" now describes a hero plus Skills and Certifications sections instead of a profile panel. "The profile panel fits the screen" is replaced by a responsive landing layout with no "Show more" toggle.

## Impact

- **Code**: `static/theme.css` (rewritten), `static/chat.html` (markup and styles rewritten, script kept with small selector updates), `static/admin-login.html` and `static/admin.html` (styles and chrome markup; scripts and IDs kept).
- **Tests**: `tests/test_theme.py` (tokens, contrast pairs, color scheme, profile-region parsing, Show-more tests removed, new structure checks). `tests/test_admin_sign_in.py` is expected to pass unchanged.
- **APIs, backend, dependencies**: none. No new packages, no external fonts or images, and no change to `app/`.
- **Other in-flight changes**: this change supersedes the "Every page is dark" requirement from `dark-theme-admin-sign-in-via-agents` and the profile-panel layout from `profile-assistant-about-kai`. Archive those changes first so these deltas apply on top of them.
