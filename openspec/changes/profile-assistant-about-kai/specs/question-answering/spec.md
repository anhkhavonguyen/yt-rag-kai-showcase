# Spec Delta

## ADDED Requirements

### Requirement: Answers list their sources
The `/answer` response SHALL include `sources`, one entry per chunk ID in `citations`, in the same order. Each entry SHALL have `chunk_id`, `title`, and `text`: the passage that was used for the answer. `title` is the title of the default document the chunk came from, or the chunk ID when that document has none. When `citations` is empty, `sources` SHALL be empty.

#### Scenario: Generated answer
- **GIVEN** retrieval returns `kai_overview_v1#1` and `kai_expertise_v1#1`
- **WHEN** the chat model's answer cites only `[kai_expertise_v1#1]`
- **THEN** `citations` is `["kai_expertise_v1#1"]`, and `sources` has one entry with that `chunk_id`, the title "Core expertise", and that chunk's passage text

#### Scenario: Fallback answer
- **GIVEN** retrieval returns passages and the chat model is unavailable
- **WHEN** `/answer` responds with `answer_mode` `extractive`
- **THEN** `sources` has one entry per citation, in the same order, each with its passage text

#### Scenario: Document without a title
- **GIVEN** the knowledge base holds `notes#1`, seeded through `/seed` from a document `notes` that isn't a default document
- **WHEN** an answer cites `notes#1`
- **THEN** its entry in `sources` has the title `notes#1`

#### Scenario: Nothing to cite
- **WHEN** `/answer` responds with `answer_mode` `no_results` or `error`
- **THEN** `sources` is an empty list
