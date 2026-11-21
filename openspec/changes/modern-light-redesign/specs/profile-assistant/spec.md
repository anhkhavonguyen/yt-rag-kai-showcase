# Spec Delta

## RENAMED Requirements

- FROM: `### Requirement: The profile panel fits the screen`
- TO: `### Requirement: The chat page layout fits the screen`

## MODIFIED Requirements

### Requirement: The chat page shows Kai's profile, skills and certifications
`/chat` SHALL show Kai's profile in its hero and in two sections below it:
- in the hero: the name Kha Vo, the nickname Kai, the LinkedIn headline, Ho Chi Minh City, Vietnam, 12+ years of experience, the current role, and a link to `https://www.linkedin.com/in/khavo2907/`;
- a "Skills" section with skills as tags in two groups, "Enterprise & cloud" and "AI";
- a "Certifications" section with the four certifications, each as a card with its issuer.

#### Scenario: Profile content
- **WHEN** `/chat` is fetched
- **THEN** the hero contains "Kha Vo", "Kai", the headline and the LinkedIn link, the Skills section contains the "Enterprise & cloud" and "AI" groups, and the Certifications section contains Claude Code in Action, AWS Educate Machine Learning Foundations, Oracle Cloud Infrastructure 2025 Certified AI Foundations Associate and Microsoft Certified Professional, with "Programming in C#" shown as its detail

#### Scenario: Same facts as the knowledge base
- **WHEN** `/chat` and `/documents` are fetched
- **THEN** every certification named on the page is also named in the education and certifications document

### Requirement: The chat page layout fits the screen
At 1024 pixels wide and wider, the hero SHALL show Kai's introduction and the chat card side by side, with the question input visible without scrolling on a 1280 by 800 window. Narrower, the introduction SHALL sit above the chat card. At every width, the Skills and Certifications sections SHALL follow the hero, fully shown, with no "Show more" button.

#### Scenario: Desktop
- **WHEN** `/chat` is shown in a 1280 by 800 window
- **THEN** the introduction and the chat card are side by side, the question input and Send button are visible without scrolling, and the Skills and Certifications sections are below the hero without pressing anything

#### Scenario: Phone
- **WHEN** `/chat` is shown 375 pixels wide
- **THEN** the introduction is above the chat card, the Skills and Certifications sections follow it fully shown, and the page doesn't scroll sideways

#### Scenario: No toggle
- **WHEN** `/chat` is fetched
- **THEN** it has no "Show more" or "Show less" button

## ADDED Requirements

### Requirement: Visitors can jump straight to the chat
The chat page SHALL offer a "Skip to chat" link as its first focusable element, and an "Ask a question" call to action in the hero. Activating either SHALL bring the chat card into view and move keyboard focus to the question input. When the chat card is in the first view (1024 pixels wide and wider), the input SHALL have focus once the page loads. Narrower, the page SHALL NOT move focus on load.

#### Scenario: Skip link
- **GIVEN** `/chat` is shown 375 pixels wide, so no element has focus after loading
- **WHEN** a keyboard user opens `/chat`, presses Tab once and then Enter
- **THEN** "Skip to chat" was shown while focused, and focus is now in the question input

#### Scenario: Hero call to action
- **GIVEN** `/chat` is shown 375 pixels wide
- **WHEN** the visitor activates "Ask a question" in the hero
- **THEN** the chat card scrolls into view and the question input has focus

#### Scenario: Focus on load
- **WHEN** `/chat` loads in a 1280 by 800 window
- **THEN** the question input has focus, and the page has not scrolled

### Requirement: Messages say who wrote them
Each chat message SHALL say who wrote it, "You" or "Kai's assistant", in text that screen readers read. The assistant's avatar SHALL be an assistant icon, not Kai's initials or photo, because the assistant talks about Kai rather than as Kai. New answers and error messages SHALL be announced to screen readers without moving focus.

#### Scenario: An answer arrives
- **GIVEN** a screen reader is running
- **WHEN** an answer arrives after the visitor asks "Who is Kai?"
- **THEN** the screen reader announces it as written by "Kai's assistant", and focus stays in the question input

#### Scenario: Avatars
- **WHEN** a question and its answer are shown
- **THEN** the question is labeled "You" and the answer "Kai's assistant", and the answer's avatar is not the initials "KV"

### Requirement: The chat page ends with a footer
`/chat` SHALL end with a footer that says the answers come from Kai's public LinkedIn profile and links to that profile. The footer SHALL NOT link to `/admin` or `/admin/login`.

#### Scenario: Footer content
- **WHEN** `/chat` is fetched
- **THEN** its footer mentions Kai's public LinkedIn profile, links to `https://www.linkedin.com/in/khavo2907/` in a new tab, and has no link to `/admin`
