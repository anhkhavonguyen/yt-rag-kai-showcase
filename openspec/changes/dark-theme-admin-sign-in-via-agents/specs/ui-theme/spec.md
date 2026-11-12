# Spec Delta

## Purpose

The shared look of every browser page the app serves: the Customer Support page, the admin sign-in page and the admin page. Keeps them dark, consistent, readable and usable with a keyboard.

## ADDED Requirements

### Requirement: Every page is dark
`/chat`, `/admin/login` and `/admin` SHALL show light text on a dark background, whatever the operating system or browser color preference. They SHALL declare a dark color scheme, so built-in controls such as inputs and scrollbars are dark too. There SHALL be no light mode and no theme toggle.

#### Scenario: Light system preference
- **GIVEN** the visitor's system is set to a light appearance
- **WHEN** they open `/chat`
- **THEN** the page has a dark background, light text and dark input fields

#### Scenario: Color scheme declared
- **WHEN** `/chat`, `/admin/login` or `/admin` is fetched
- **THEN** the page declares the dark color scheme, and contains no theme toggle

### Requirement: Pages share one stylesheet
`/chat`, `/admin/login` and `/admin` SHALL load the same stylesheet, `/static/theme.css`, which defines every palette color. The pages' own styles SHALL NOT contain hex color values, so a color changes in one place.

#### Scenario: Stylesheet served
- **WHEN** `GET /static/theme.css` is sent
- **THEN** the response is 200 with a CSS content type

#### Scenario: Pages link it and define no colors of their own
- **WHEN** `/chat`, `/admin/login` and `/admin` are fetched (with sign-in where needed)
- **THEN** each page links `/static/theme.css`, and its inline `<style>` and `style` attributes contain no hex color values

### Requirement: Text and controls have enough contrast
In the shared palette, every text color SHALL have a contrast ratio of at least 4.5:1 against each background it is used on. This includes normal, muted, error and button text. Button backgrounds and the focus indicator SHALL have at least 3:1 against the page background.

#### Scenario: Muted text on a card
- **WHEN** the muted text color is measured against the page background and the card background
- **THEN** both ratios are at least 4.5:1

#### Scenario: Button
- **WHEN** the button text color is measured against the button background, and the button background against the page background
- **THEN** the first ratio is at least 4.5:1 and the second at least 3:1

### Requirement: Keyboard focus is visible
Every link, button and input on the three pages SHALL show a visible focus indicator when reached with the keyboard, in a color with at least 3:1 contrast against the page background.

#### Scenario: Tabbing through the sign-in page
- **WHEN** the owner presses Tab to move from the token field to the "Sign in" button
- **THEN** each element shows a focus outline while focused

### Requirement: Pages fit a phone screen
The three pages SHALL be usable at 375 pixels wide without horizontal scrolling, with every control visible and usable.

#### Scenario: Customer Support on a phone
- **WHEN** `/chat` is shown 375 pixels wide
- **THEN** the page does not scroll sideways, and the input and Send button are fully visible

### Requirement: Pages load nothing from other sites
The three pages and the shared stylesheet SHALL NOT load scripts, stylesheets, fonts or images from another origin.

#### Scenario: No external resources
- **WHEN** `/chat`, `/admin/login`, `/admin` and `/static/theme.css` are fetched
- **THEN** none of them references an `http://` or `https://` URL in a `src` attribute, a stylesheet link or a CSS `url()`

### Requirement: The Customer Support page keeps its content and behavior
The dark theme SHALL change only how `/chat` looks. The page SHALL keep the title and heading "Customer Support", its subtitle and welcome message, the status line, the question input and Send button, and how it calls `/healthz` and `/answer`. It SHALL still have no link to `/admin`.

#### Scenario: Asking a question
- **GIVEN** the knowledge base is seeded
- **WHEN** a visitor asks about returns on `/chat`
- **THEN** the answer appears with its sources, as before this change

#### Scenario: Still no admin entry
- **WHEN** `/chat` is fetched
- **THEN** the page contains no link to `/admin` or `/admin/login`
