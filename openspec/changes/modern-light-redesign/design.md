# Design

## Context

- The site is three static pages served by FastAPI: [static/chat.html](../../../static/chat.html), [static/admin-login.html](../../../static/admin-login.html) and [static/admin.html](../../../static/admin.html). They share [static/theme.css](../../../static/theme.css). There is no build step or framework: plain HTML, CSS and inline scripts.
- Every color lives in `theme.css` as a `#rrggbb` token. Pages may not contain hex colors. [tests/test_theme.py](../../../tests/test_theme.py) enforces the token list, WCAG contrast pairs, the color scheme, no external resources and the `/chat` content.
- Pages may load nothing from other origins, which rules out Google Fonts, CDNs and remote images.
- Today `/chat` is a boxed "app window" (90vh card) with a 320px profile `<aside>` beside the chat. Below 900px the profile collapses behind "Show more". The chat uses emoji avatars and emoji in its messages.
- The reference, the DEKRA home page, has these patterns: a slim top bar, a short and very wide hero band with one headline and one call to action, teaser cards in a grid, sentence-case headings, green used sparingly (logo, accents), most color carried by imagery, and a dark footer band.

## Goals / Non-Goals

**Goals:**
- One light design system in `theme.css` that all three pages draw from: tokens, type, spacing, components.
- `/chat` reads as a professional profile landing page, and the chat stays in the first view on desktop.
- Keep every existing behavior and element ID that scripts and tests depend on. Restyle and restructure the markup around them.
- Accessibility at least as good as today: AA contrast, visible focus, keyboard paths, reduced motion, and screen-reader announcements for answers.

**Non-Goals:**
- Copying DEKRA's brand. We borrow layout patterns, not the logo, wordmark, exact brand green, photography, decorative logo shape, mega menu or carousel.
- A JavaScript framework, CSS preprocessor, build step or icon library.
- Changing admin behavior. That includes ARIA tab semantics for the admin tabs, the admin `innerHTML` document rendering, and the stale Settings tab values. Each would be its own change.

## Decisions

### 1. Light palette: re-value the existing tokens and add band tokens
The 13 existing token names stay, so every `var(--…)` in the pages keeps working, and they get light values. Seven tokens are added. Proposed values (each pair below was computed with the same formula as `test_theme.py`):

| Token | Value | Role | Key contrast |
|---|---|---|---|
| `--bg` | `#f5f7f6` | page background | — |
| `--surface` | `#ffffff` | cards, top bar | — |
| `--surface-raised` | `#eef2f0` | assistant bubbles, hover rows | — |
| `--text` | `#16201b` | body text | 15.5 on bg |
| `--text-muted` | `#4f5b55` | secondary text | 6.3 on surface-raised |
| `--accent` | `#00733f` | primary buttons, links, highlights | 5.3 on surface-raised, 5.2 on chip-bg |
| `--accent-strong` *(new)* | `#005c32` | hover/pressed accent | white on it 8.2 |
| `--on-accent` | `#ffffff` | text on accent | 6.0 |
| `--border` | `#dce3df` | dividers, card outlines (decorative) | — |
| `--border-strong` *(new)* | `#7d8983` | input and secondary-button borders | 3.2 on surface-raised |
| `--danger` | `#b3261e` | errors | 6.1 on bg |
| `--success` | `#1d7a46` | success | 5.0 on bg |
| `--focus` | `#16201b` | focus ring on light surfaces | 14.5 on chip-bg |
| `--tag-bg` | `#e7f1ec` | skill tags | text 14.5 |
| `--chip-bg` | `#e7f1ec` | sample-question chips | accent 5.2 |
| `--hero-bg` *(new)* | `#0b3a27` | hero band | — |
| `--footer-bg` *(new)* | `#141a17` | footer band | — |
| `--on-band` *(new)* | `#ffffff` | text on bands | 12.7 on hero |
| `--on-band-muted` *(new)* | `#c3d3ca` | secondary text on bands | 8.2 on hero |
| `--focus-on-band` *(new)* | `#ffd166` | focus ring on bands | 8.8 on hero |

- The accent is a deep green in the reference's family, not its brand value. It is darker than `#008143`, so link text still passes 4.5:1 on the pale green chips.
- Accent green on the hero band is only 2.1:1. So inside bands, the primary button is **white with hero-green text** (`.button-on-band`), and the secondary is a white outline.
- Non-color tokens (spacing, radii, shadows as `rgba`, widths) also live in `:root`. Only the 20 color tokens above must be hex. Pages reference shadows by token, so they still contain no colors.
- **Alternative considered:** a dual light/dark palette that follows `prefers-color-scheme`. The owner chose a single light palette, and dual palettes double the contrast matrix.

### 2. Typography: system font stack with a bold scale
- Stack: `"Segoe UI Variable Text", "Segoe UI", system-ui, -apple-system, BlinkMacSystemFont, "Helvetica Neue", Arial, sans-serif`. Headings use `"Segoe UI Variable Display"` first.
- Scale (fluid with `clamp()`): h1 ≈ 36→56px at weight 700 with −0.02em tracking; h2 ≈ 24→32px at 700; card titles 18px at 600; body 16px with line-height 1.6; small 14px; one small uppercase eyebrow label with +0.08em tracking. All other text is sentence case, as on the reference.
- **Alternative considered:** self-hosting Inter (OFL) from `static/fonts`. Rejected: it adds 100–300 KB, a license file and a `@font-face` exception, while Segoe UI Variable and SF already look modern. The spec now says no page loads a font file, so adding one later would be a spec change.

### 3. Shared components in `theme.css`
Pages keep only layout-specific styles. `theme.css` gains:
- `.top-bar`, `.wordmark` (a small CSS-drawn accent square plus "Meet Kai"), `.badge` ("Admin");
- `.container` (max 1200px, 16–32px gutters), `.section`, `.section-header`, `.eyebrow`;
- `.card` (white, 1px `--border`, radius 16px, soft shadow token);
- `.button-primary`, `.button-secondary`, `.button-on-band`, `.button-outline-on-band`, each with an optional trailing arrow icon;
- `.chip` (pill, `--chip-bg`, accent text), `.tag` (pill, `--tag-bg`);
- `.field` (inputs and textareas: white, `--border-strong`, radius 10px, accent border on focus);
- `.skip-link`, `.visually-hidden`, `.band` (hero/footer: switches text and focus colors to the band tokens);
- global `:focus-visible` (2px `--focus` outline, 2px offset), overridden inside `.band` to `--focus-on-band`;
- a `@media (prefers-reduced-motion: reduce)` block that turns off animations and transitions.

Existing class names that scripts or tests use stay as they are: `button-primary`, `button-secondary`, `sample-question`, `status connected|warning|error`, `save-button loading|success|error`, `notification success|error|info`, `text-error`, `text-success`.

### 4. `/chat` layout: hero with the chat built in

```
Desktop (≥1024px)                                Phone (<1024px)
┌──────────────────────────────────────────────┐ ┌──────────────────────┐
│ ■ Meet Kai     Chat Skills Certifications  in↗│ │ ■ Meet Kai     Chat  │ sticky top bar
├──────────────────────────────────────────────┤ ├──────────────────────┤
│▓ KHA VO · KNOWN AS KAI   ┌──────────────────┐▓│ │▓ KHA VO · KNOWN AS…  ▓│ hero band
│▓ Meet Kai                │ ✦ Kai's assistant│▓│ │▓ Meet Kai            ▓│ (--hero-bg)
│▓ Ask about Kha Vo's…     │      ● System…   │▓│ │▓ Ask about …         ▓│
│▓ Team Lead | Enterprise… │ messages…        │▓│ │▓ headline · facts    ▓│
│▓ HCMC · 12+ yrs · role   │ [chip][chip]     │▓│ │▓ [Ask a question →]  ▓│
│▓ [Ask a question →][in↗] │ [input……][Send ➤]│▓│ │▓ [LinkedIn ↗]        ▓│
├──────────────────────────┴──────────────────┴─┤ ├──────────────────────┤
│ Skills                                        │ │ ┌──────────────────┐ │ chat card
│ ┌ Enterprise & cloud ──┐ ┌ AI ────────────────┐│ │ │ chat …           │ │
│ │ [C#][.NET][Azure]…   │ │ [LLMs][RAG]…       ││ │ └──────────────────┘ │
│ └──────────────────────┘ └────────────────────┘│ │ Skills (cards)       │
│ Certifications                                 │ │ Certifications       │
│ [card][card][card][card]                       │ │ [card] [card] …      │
├────────────────────────────────────────────────┤ ├──────────────────────┤
│▓ ■ Meet Kai · Answers come from Kai's public… ▓│ │▓ footer             ▓│ footer band
└────────────────────────────────────────────────┘ └──────────────────────┘
```

- **Hero grid:** two columns at ≥1024px (`minmax(340px, 5fr) minmax(480px, 6fr)`). The chat card hangs about 48px below the band into the light page, so it reads as lifted. Below 1024px, it is one column: the intro, then the chat card.
- **Chat card height:** desktop `min(680px, 100dvh − top bar − 48px)`, with a `vh` fallback, so the input is visible at 1280×800. Phone: `min(640px, 80dvh)`. Messages scroll inside the card.
- **Profile regions:** the hero intro is `id="about"` (name, "Known as Kai", headline, facts, LinkedIn), with `id="skills"` and `id="certifications"` as sections. Tests parse these ids instead of `<aside>`. The `<aside>`, `#profile-more`, `#profileMoreToggle` and their script are removed.
- **Anchors and the sticky bar:** `html { scroll-padding-top: var(--topbar-h) }`, so anchored sections aren't hidden under the bar. Below 640px the top bar shows only the wordmark and "Chat", which keeps it to one line. LinkedIn is still in the hero and the footer.
- **Skills:** two cards side by side from 768px, each with a title and a tag list.
- **Certifications:** a 1/2/4-column grid of cards (name, issuer · date or detail, optional "Verify ↗" link). The four certifications are plain markup, as today.
- **Decorative hero background:** a flat `--hero-bg` with a faint radial highlight drawn in `theme.css`. There are no images. Band text contrast is checked against the flat color, and the highlight is low enough that `--on-band-muted` keeps well over 4.5:1.

### 5. The chat card: restyle without changing behavior
- **Header:** an assistant avatar (inline SVG sparkle on `--chip-bg`), the title "Kai's assistant", the subline "Answers from Kai's LinkedIn profile, with sources", and `#status` as a pill with a colored dot. The status texts are unchanged.
- **Messages:** assistant bubbles on `--surface-raised`, user bubbles in `--accent` with white text, radius 16px with one tighter corner, and no heavy shadows. Only the assistant shows an avatar. Each message starts with a visually hidden label, "You:" or "Kai's assistant:".
- **Avatar markup:** the script clones the avatar from a `<template id="assistant-avatar">` with inline SVG. No `innerHTML`, so the plain-text test still holds.
- **Announcements:** `#messages` gets `role="log"` (polite live region), so screen readers announce answers and errors without moving focus. The typing indicator is visible text, "Thinking", plus decorative dots marked `aria-hidden`.
- **Sample questions:** `.chip.sample-question`, same buttons, same script.
- **Sources:** `<details>` rows with a number badge and a chevron, with the passage in a muted inset block. The mode line stays as small muted text.
- **Input bar:** a `.field` input plus `.button-primary` Send with an inline SVG icon (`aria-hidden`) and the text "Send". Below 480px the text is visually hidden, so the accessible name stays "Send".
- **Emoji removed** from page-written strings: "Hi! 👋", 🔧, 🔌, ✨/👤/💭 avatars. The error message wording otherwise stays the same.
- **Focus on load:** `messageInput.focus({ preventScroll: true })` only when `matchMedia('(min-width: 1024px)')` matches, because only then is the input in the first view. On phones, focusing on load would skip screen-reader users past the hero. The skip link and the hero call to action both call one `focusChat()` helper (`scrollIntoView` plus focus).

### 6. Admin pages
- **Both pages:** the shared top bar with the wordmark and an "Admin" badge, and a "Back to chat" link on the right. `/admin` also has Sign out (`#signOutBtn`) there. The body is no longer a boxed 90vh window. It is a normal page with a container.
- **`/admin/login`:** a centered `.card` (max 420px) with a thin accent rule on top, "Admin sign in", the intro, the labeled `.field` and a full-width primary button. All IDs and scripts are unchanged.
- **`/admin`:**
  - The page header is "Knowledge Base Editor" (📋 dropped) with its subtitle.
  - Underline tabs, with the active tab in accent and a 2px underline.
  - Each document is a `.card` with the chunk id in a monospace label, the source in muted text, and the textarea as `.field`.
  - A **sticky save bar** at the bottom of the viewport holds Save (`.button-primary` plus the existing state classes).
  - The Settings tab's inline `style=` attributes become classes. Its text is unchanged.
  - The toast becomes a white card with a colored left border and an icon.
  - Strings drop emoji: "Save", "Saving…", "Saved", "Save failed", and "Saved N chunks, removed M old ones".
  - The save-button label is now set with `textContent`, since its strings change anyway.
- **Inline sign-in gate:** same `hidden` swap, styled like the sign-in card.

### 7. Tests
`tests/test_theme.py` is updated in step with the markup:
- the token list (+7), contrast pairs (links, `--border-strong`, band text, band focus), `color-scheme: light`, a `content="light"` meta, and the luminance check reversed;
- the profile region parsed from `#about`, `#skills` and `#certifications`;
- the Show-more test removed, and a no-toggle test added;
- a `min-width: 1024px` media query instead of 900px;
- new checks: a top bar with the wordmark on all three pages, a skip link as the first link, `role="log"` on messages, "Kai's assistant" in the script, a footer with LinkedIn and no `/admin`, no `@font-face`, a `prefers-reduced-motion` block in `theme.css`, and no emoji code points in the three pages;
- the Send test switched to the button's text content, and the admin save-message assertion updated to the emoji-free text.

Layout at 375/1280×800, keyboard paths and reduced motion are checked by hand in a browser, as before.

## Risks / Trade-offs

- [The deltas modify requirements that exist only in two in-flight changes] → Archive `dark-theme-admin-sign-in-via-agents` and `profile-assistant-about-kai` before this change. `openspec validate` already flags this as info.
- [Hero columns get tight between 1024 and 1180px] → Use `minmax()` minimums with the intro text allowed to wrap, and check at 1024px by hand. If it's still cramped, raise the breakpoint to 1100px. Only the test's media-query value changes.
- [System fonts differ by OS, so the look varies slightly] → Variable Segoe/SF give a modern baseline. Hand-check on Windows and one phone.
- [`100dvh` isn't supported everywhere] → Declare the `vh` value first and override it with `dvh`.
- [`test_theme.py` bans the strings "dark mode", "light mode", "theme toggle" and "prefers-color-scheme" anywhere in page HTML] → Keep them out of comments too. The token comment in `theme.css` says "single light palette".
- [Visitors could read a DEKRA-like look as an affiliation] → Use our own green and wordmark, and no DEKRA marks or imagery. DEKRA appears only in the factual role line, as today.
- [The sticky save bar could cover the last document's textarea] → Add bottom padding to the document list equal to the bar's height.

## Migration Plan

1. Land everything on a branch in one PR: `theme.css`, the three pages and `tests/test_theme.py` together. The token re-values change every page at once, so no page should ever see a mixed theme.
2. Run `pytest` locally and in CI, then hand-check `/chat`, `/admin/login` and `/admin` at 375px and 1280×800, by keyboard and with reduced motion on.
3. Deploy through the existing Render flow. The change is static files only, with no environment, database or API changes.
4. **Rollback:** revert the PR. There is no data or config to undo.

## Open Questions

- The exact wording of the hero eyebrow, the chat-card subline and the footer line can be polished after the owner previews the page. Wording changes don't affect the specs as long as the required texts stay.
