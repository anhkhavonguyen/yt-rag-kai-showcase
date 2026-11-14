# Spec Delta

## RENAMED Requirements

- FROM: `### Requirement: The Customer Support page keeps its content and behavior`
- TO: `### Requirement: The chat page keeps its content and behavior`

## MODIFIED Requirements

### Requirement: The chat page keeps its content and behavior
The dark theme SHALL change only how `/chat` looks. The page SHALL keep the content the `profile-assistant` capability gives it (the title and heading "Meet Kai", its subtitle, welcome message and sample questions, the profile panel and the answer details), the status line, the question input and Send button, and how it calls `/healthz` and `/answer`. It SHALL still have no link to `/admin`.

#### Scenario: Asking a question
- **GIVEN** the knowledge base is seeded
- **WHEN** a visitor asks "Who is Kai?" on `/chat`
- **THEN** the answer appears with its sources, as before this change

#### Scenario: Still no admin entry
- **WHEN** `/chat` is fetched
- **THEN** the page contains no link to `/admin` or `/admin/login`
