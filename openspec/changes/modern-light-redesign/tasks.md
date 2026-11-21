# Tasks

**Build approach.** Implement with Claude Code directly. Don't run the agent orchestrator, and make no Gemini calls while building: the free quota is kept for the owner's testing.
- Tests use the fakes in `tests/conftest.py`.
- For local browser checks, start the app with `uvicorn main:app --reload --port 8000`. Don't send a question, click a sample question or press Save on `/admin`: each of those calls Gemini through `/answer` or `/seed`.
- To see answers, sources and admin toasts, render them from the DevTools console. For example, `addMessage('Kai leads… [kai_overview_v1]', false, [{chunk_id: 'kai_overview_v1', title: 'Who Kai is', text: '…'}], {answer_mode: 'generated', latency_ms: 1234})` on `/chat`, or `showNotification('Saved 3 chunks, removed 1 old ones', 'success')` on `/admin`.

**Branch.** Run `git fetch` first. Then create the branch `modern-light-redesign` from `origin/main`, which already has the profile-assistant pages. Local `main` is stale.

## 1. Setup

- [x] 1.1 Create the branch from `origin/main` and bring this change's `openspec/changes/modern-light-redesign/` folder along. Verify: `pytest` and `ruff check .` pass before any edits, and `openspec validate modern-light-redesign --strict` reports the change valid.

## 2. Light design system in `theme.css` (spec: ui-theme)

- [x] 2.1 Re-value the 13 color tokens and add the 7 new ones from design decision 1. Set `color-scheme: light`, and rewrite the header comment's contrast list for the new pairs (don't use the phrases "dark mode", "light mode" or "theme toggle"). Change `<meta name="color-scheme">` to `light` in all three pages. In `tests/test_theme.py`:
  - extend `TOKENS`;
  - replace `CONTRAST_PAIRS` with the pairs in the ui-theme contrast requirement: text, muted, link, error, success and button text; `--border-strong` at 3:1; `--on-band` and `--on-band-muted` on `--hero-bg` and `--footer-bg`; `--focus` on the light surfaces and chips; `--focus-on-band` on both bands;
  - change the scheme tests to light, with dark text on a light `--bg`.

  Verify: `pytest tests/test_theme.py` passes, and temporarily setting `--accent` to `#2e9e5b` makes the accent-on-chip-bg contrast test fail.
- [x] 2.2 Add non-color tokens to `:root`: spacing scale, radii, `rgba` shadow tokens, `--topbar-h` and `--content-max`. Add the font stacks and the fluid type scale (decision 2), base heading and body styles, and link styles (accent, hover `--accent-strong`, visible underline offset). Add a test that `theme.css` sets a `font-family` and that no page or stylesheet contains `@font-face`. Verify: `pytest tests/test_theme.py` passes.
- [x] 2.3 Add the shared components from decision 3: `.top-bar`, `.wordmark`, `.badge`, `.container`, `.section`, `.section-header`, `.eyebrow`, `.card`, the four button variants (with hover and disabled states), `.chip`, `.tag`, `.field`, `.skip-link`, `.visually-hidden` and `.band`. Add the global `:focus-visible` outline in `--focus`, overridden inside `.band` to `--focus-on-band`. Add tests:
  - `theme.css` defines `.button-primary`, `.button-secondary`, `.card`, `.chip`, `.tag`, `.field` and `.top-bar`;
  - the `:focus-visible` rule uses `var(--focus)`;
  - a `.band` focus rule uses `var(--focus-on-band)`.

  Verify: `pytest tests/test_theme.py` passes.
- [x] 2.4 Add motion rules: transitions of at most 300 ms, and a `@media (prefers-reduced-motion: reduce)` block that removes animations and movement transitions. Add tests:
  - `theme.css` has the reduced-motion block;
  - every `transition` and `animation` duration in `theme.css` and the three pages is ≤ 300 ms, except the typing-dots animation.

  Verify: `pytest tests/test_theme.py` passes.

## 3. `/chat` as a profile landing page with the chat built in (specs: profile-assistant, ui-theme)

- [x] 3.1 Restructure `static/chat.html` markup as in design decision 4:
  - a skip link (`href="#chat"`, "Skip to chat");
  - a top bar with the wordmark, Chat/Skills/Certifications anchors and LinkedIn ↗;
  - the hero `.band`, holding the `#about` intro (eyebrow, `<h1>Meet Kai</h1>`, the subtitle "Ask about Kha Vo's experience, skills and work", headline, facts, "Ask a question" and LinkedIn ↗ calls to action) and the `#chat` card;
  - `#skills` and `#certifications` sections;
  - a footer `.band` that says answers come from Kai's public LinkedIn profile and links to it.

  Keep the IDs `status`, `messages`, `typing`, `messageInput` and `sendBtn`, and keep all existing texts. Remove the `<aside>`, `#profile-more`, `#profileMoreToggle` and their script. In `tests/test_theme.py`:
  - parse the profile from `#about`, `#skills` and `#certifications` instead of `<aside>`;
  - delete the Show-more test, and add a test that no button says "Show more" or "Show less";
  - add a top-bar test (wordmark, three anchors, LinkedIn, no `/admin`);
  - add a footer test (LinkedIn link in a new tab, no `/admin`).

  Verify: `pytest tests/test_theme.py` passes. The existing tests for external links, certification links, the education document and "no admin entry" pass unchanged.
- [x] 3.2 Write the page layout CSS:
  - the hero grid at `@media (min-width: 1024px)`, with the chat card overhanging the band by about 48px;
  - chat card heights with a `vh` fallback, then `dvh`;
  - single-column stacking below 1024px;
  - skills in two columns from 768px;
  - certifications in a 1/2/4-column grid;
  - `scroll-padding-top: var(--topbar-h)`;
  - the top bar reduced to the wordmark and "Chat" below 640px.

  Change the layout test from 900px to 1024px. Verify: `pytest tests/test_theme.py` passes. By hand: at 1280×800 the input and Send are visible without scrolling; at 1024px the hero columns don't overlap; at 375px nothing scrolls sideways and the top bar is one line.
- [x] 3.3 Restyle the chat card (decision 5):
  - a header with the assistant avatar `<template>`, "Kai's assistant", the subline and `#status` as a pill with a colored dot (status texts unchanged);
  - assistant and user bubbles;
  - `.chip.sample-question` chips;
  - sources as `<details>` rows with number badges;
  - the muted mode line;
  - an input bar with the `.field` input and a `.button-primary` Send that has an `aria-hidden` SVG icon plus the text "Send", visually hidden below 480px;
  - the "Thinking" typing indicator with `aria-hidden` dots.

  Change the Send test to check the button's text content is "Send". Verify: `pytest tests/test_theme.py` passes. In the DevTools console, render a generated answer with two sources, an extractive answer, and a `no_results` answer. Each matches the spec: numbered collapsed sources, the "AI answer · 1.2 s" line, and no sources or mode line for `no_results`.
- [x] 3.4 Update the chat script:
  - `addMessage` adds a visually hidden "You:" or "Kai's assistant:" label and clones the avatar template (no `innerHTML`);
  - `#messages` gets `role="log"`;
  - one `focusChat()` helper serves the skip link and the hero call to action;
  - focus on load only when `matchMedia('(min-width: 1024px)')` matches;
  - remove emoji from the welcome and error strings.

  Add tests:
  - `role="log"` is on `#messages`;
  - the script contains "Kai's assistant";
  - the first link in the page is the skip link to `#chat`;
  - an "Ask a question" call to action exists;
  - the script uses `min-width: 1024px` with `matchMedia`;
  - `chat.html` contains no emoji code points.

  Verify: `pytest tests/test_theme.py` passes, including the existing plain-text, sample-question and pending tests. By hand: on load at 1280×800, focus is in the input. At 375px, Tab once shows "Skip to chat" and Enter moves focus to the input. Tapping "Ask a question" scrolls the chat card into view and focuses the input.

## 4. Admin pages in the new look (spec: ui-theme)

- [x] 4.1 Restyle `static/admin-login.html` (decision 6): a top bar with the wordmark, "Admin" badge and "← Back to chat" link, and a centered `.card` with an accent rule, the `.field` token input and a full-width `.button-primary`. Keep all IDs, texts and the script. Verify: `pytest tests/test_admin_sign_in.py tests/test_theme.py` passes, including the back-link test. By hand: an empty submit shows "Enter the admin token", and Tab moves visibly through the field, the button and the link.
- [x] 4.2 Restyle `static/admin.html` (decision 6):
  - a top bar with the wordmark, "Admin" badge, "← Back to chat" and `#signOutBtn`;
  - a page header "Knowledge Base Editor" without emoji;
  - underline tabs;
  - document `.card`s with a monospace chunk id and a `.field` textarea;
  - a sticky save bar with Save as `.button-primary` plus the existing state classes, and bottom padding on the list;
  - the Settings tab's inline styles moved to classes;
  - the toast restyled;
  - the inline sign-in gate styled like the sign-in card.

  Change the save strings to "Save", "Saving…", "Saved", "Save failed" and "Saved ${data.inserted} chunks, removed ${data.removed} old ones", and set the label with `textContent`. Update the admin save-message assertion in `tests/test_theme.py`. Verify: `pytest tests/test_admin_sign_in.py tests/test_theme.py` passes. By hand, at 375px and 1280px:
  - tabs switch;
  - the last document isn't hidden behind the save bar;
  - `showNotification(…, 'success'|'error')` renders correctly from the console;
  - removing the session cookie and calling `showSignIn()` shows the gate with edits kept.
- [x] 4.3 Extend the shared checks to all three pages: a top bar with the "Meet Kai" wordmark on `/admin/login` and `/admin` (with the admin label and a `/chat` link), Send, Sign in and Save carrying `button-primary`, and no emoji code points in `admin-login.html` or `admin.html`. Verify: `pytest tests/test_theme.py` passes.

## 5. Integration checks

- [ ] 5.1 Run the whole suite and the linter. Verify: `pytest` and `ruff check .` pass locally, and the CI workflow passes on the pushed branch.
- [ ] 5.2 Hand-check all three pages in a local browser, without sending questions or saving:
  - 375px and 1280×800 layouts;
  - Tab through every page, with the focus ring visible on light surfaces and on the hero and footer bands;
  - DevTools "prefers-reduced-motion: reduce" (no sliding, fading or bouncing dots);
  - DevTools "prefers-color-scheme: dark" (pages stay light);
  - Lighthouse accessibility on `/chat` scores at least 95.

  Verify: the results are recorded in the PR description.
- [x] 5.3 Re-run `openspec validate modern-light-redesign --strict`. Verify: it reports the change valid. The only info lines are the expected "target spec does not exist" notes, resolved by the archive order below.

## Workflow follow-up

- Open the PR for review, then deploy through the existing Render flow after merge. The change is static files only.
- Archive `dark-theme-admin-sign-in-via-agents` and `profile-assistant-about-kai` before archiving this change, so its `ui-theme` and `profile-assistant` deltas apply on top of theirs.
