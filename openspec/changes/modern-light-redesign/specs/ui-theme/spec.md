# Spec Delta

## RENAMED Requirements

- FROM: `### Requirement: Every page is dark`
- TO: `### Requirement: Every page uses one light palette`

## MODIFIED Requirements

### Requirement: Every page uses one light palette
`/chat`, `/admin/login` and `/admin` SHALL show dark text on light backgrounds, whatever the operating system or browser color preference. Dark backgrounds SHALL appear only in the `/chat` hero and footer bands. The pages SHALL declare a light color scheme, so built-in controls such as inputs and scrollbars are light too. There SHALL be one palette: no dark mode and no theme toggle.

#### Scenario: Dark system preference
- **GIVEN** the visitor's system is set to a dark appearance
- **WHEN** they open `/chat`
- **THEN** the page has light backgrounds, dark text and light input fields, and only the hero and footer bands are dark

#### Scenario: Color scheme declared
- **WHEN** `/chat`, `/admin/login` or `/admin` is fetched
- **THEN** the page declares the light color scheme, and contains no theme toggle

### Requirement: Text and controls have enough contrast
In the shared palette, every text color SHALL have a contrast ratio of at least 4.5:1 against each background it is used on. This includes normal, muted, link, error, success and button text, and text on the dark hero and footer bands. Button backgrounds, the borders of inputs and the focus indicator SHALL have at least 3:1 against the background they sit on.

#### Scenario: Muted text on a card
- **WHEN** the muted text color is measured against the page background and the card background
- **THEN** both ratios are at least 4.5:1

#### Scenario: Button
- **WHEN** the button text color is measured against the button background, and the button background against the page background
- **THEN** the first ratio is at least 4.5:1 and the second at least 3:1

#### Scenario: Links and source titles on light surfaces
- **WHEN** the link color is measured against the page, card and raised-card backgrounds, and against the sample-question chip background
- **THEN** every ratio is at least 4.5:1

#### Scenario: Text on the dark bands
- **WHEN** the band text and muted band text colors are measured against the hero and footer backgrounds
- **THEN** every ratio is at least 4.5:1

#### Scenario: Input border
- **WHEN** the input border color is measured against the page and card backgrounds
- **THEN** both ratios are at least 3:1

### Requirement: Keyboard focus is visible
Every link, button, input and source title on the three pages SHALL show a visible focus indicator when reached with the keyboard, with at least 3:1 contrast against the background it appears on. This includes links and buttons inside the dark hero and footer bands.

#### Scenario: Tabbing through the sign-in page
- **WHEN** the owner presses Tab to move from the token field to the "Sign in" button
- **THEN** each element shows a focus outline while focused

#### Scenario: Tabbing through the hero
- **WHEN** a visitor presses Tab to reach the calls to action in the `/chat` hero
- **THEN** each one shows a focus outline that is clearly visible against the dark band

### Requirement: Pages fit a phone screen
The three pages SHALL be usable at 375 pixels wide without horizontal scrolling, with every control visible and usable.

#### Scenario: Chat page on a phone
- **WHEN** `/chat` is shown 375 pixels wide
- **THEN** the page does not scroll sideways, the top bar fits on one line, and the question input and Send button are fully visible once the chat card is scrolled into view

#### Scenario: Admin editor on a phone
- **WHEN** `/admin` is shown 375 pixels wide to a signed-in owner
- **THEN** the page does not scroll sideways, and the tabs, document fields, Save and Sign out are fully visible and usable

### Requirement: The chat page keeps its content and behavior
The redesign SHALL change how `/chat` looks and is laid out, not what it does. The page SHALL keep the content the `profile-assistant` capability gives it: the title and heading "Meet Kai", its subtitle, welcome message and sample questions, Kai's profile, skills and certifications, and the answer details. It SHALL also keep the status line, the question input and Send button, and how it calls `/healthz` and `/answer`. It SHALL still have no link to `/admin`.

#### Scenario: Asking a question
- **GIVEN** the knowledge base is seeded
- **WHEN** a visitor asks "Who is Kai?" on `/chat`
- **THEN** the answer appears with its sources, as before this change

#### Scenario: Still no admin entry
- **WHEN** `/chat` is fetched
- **THEN** the page contains no link to `/admin` or `/admin/login`

## ADDED Requirements

### Requirement: Pages share one set of components
The shared stylesheet SHALL define the font stack, the type scale and the styles of primary and secondary buttons, cards, chips, tags, form fields and the top bar. Each page SHALL use these shared styles for its buttons, cards and form fields instead of styling its own versions. No page SHALL load a font file.

#### Scenario: Shared styles defined
- **WHEN** `/static/theme.css` is fetched
- **THEN** it defines a font family and styles for primary and secondary buttons, cards, chips, tags, form fields and the top bar

#### Scenario: Primary actions look the same everywhere
- **WHEN** `/chat`, `/admin/login` and `/admin` are fetched
- **THEN** Send, Sign in and Save all use the shared primary button style, and no page or stylesheet declares `@font-face`

### Requirement: Every page starts with a top bar
Each of the three pages SHALL start with a top bar showing the "Meet Kai" wordmark. On `/chat` the bar SHALL stay visible while the page scrolls and link to the page's chat, skills and certifications sections and to Kai's LinkedIn profile. On `/admin/login` and `/admin` the bar SHALL label the page as admin and link back to `/chat`.

#### Scenario: Chat page top bar
- **WHEN** `/chat` is fetched
- **THEN** its top bar contains the "Meet Kai" wordmark, links to the chat, skills and certifications sections of the page, and a link to `https://www.linkedin.com/in/khavo2907/`, and no link to `/admin`

#### Scenario: Scrolling the chat page
- **WHEN** a visitor scrolls `/chat` down to the certifications
- **THEN** the top bar is still visible at the top of the window

#### Scenario: Admin top bar
- **WHEN** `/admin` is shown to a signed-in owner
- **THEN** its top bar shows the "Meet Kai" wordmark with an admin label, a link back to `/chat`, and the Sign out button

### Requirement: Motion is calm and can be turned off
Animations and transitions on the three pages SHALL last at most 300 ms. Nothing SHALL move or change on its own, apart from the typing indicator while an answer is pending. When the visitor's system asks for reduced motion, the pages SHALL show no movement animations or transitions.

#### Scenario: Reduced motion
- **GIVEN** the visitor's system asks for reduced motion
- **WHEN** they send a question on `/chat` and the answer arrives
- **THEN** the messages appear without sliding or fading, and the typing indicator shows "Thinking" without bouncing dots

#### Scenario: Nothing advances on its own
- **WHEN** `/chat` is left open without input
- **THEN** no content rotates, slides or auto-advances

### Requirement: Icons are decorative or named
Icons SHALL be drawn inline in the page, with no image files from other sites. A decorative icon SHALL be hidden from assistive technology. A control that shows only an icon SHALL have an accessible name. Emoji SHALL NOT be used in the page's own interface text: headings, buttons, avatars, the status line, and the welcome, error and notification messages the page writes.

#### Scenario: Send button
- **WHEN** the `/chat` Send button shows an icon
- **THEN** its accessible name is "Send" and the icon is hidden from screen readers

#### Scenario: No emoji in the interface
- **WHEN** `/chat`, `/admin/login` and `/admin` are fetched
- **THEN** no heading, button, avatar, status text, or message string written in the page contains an emoji

### Requirement: The admin pages keep their content and behavior
The redesign SHALL change only how `/admin/login` and `/admin` look. The sign-in page SHALL keep its heading, its labeled token field, Sign in, its error messages and a link back to `/chat`. The admin page SHALL keep the title "Knowledge Base Editor", the Documents and Settings tabs, the document editor, Save, Sign out, a link back to `/chat`, and the inline sign-in shown when Save is refused.

#### Scenario: Wrong token
- **WHEN** the owner submits a wrong token on `/admin/login`
- **THEN** the page shows "Admin token rejected", as before this change

#### Scenario: Saving
- **GIVEN** a signed-in owner has edited a document on `/admin`
- **WHEN** they press Save and the save succeeds
- **THEN** the page reports how many chunks were saved and how many old ones were removed, as before this change

#### Scenario: Session ended while editing
- **GIVEN** the owner's session has ended
- **WHEN** they press Save on `/admin`
- **THEN** the inline sign-in appears and their unsaved edits stay in the page, as before this change
