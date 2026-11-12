# Spec Delta

## Purpose

Defines how `/answer` responds to a question. When the language model is unavailable, the user still gets cited content, and the response says how its answer was produced.

## ADDED Requirements

### Requirement: Retrieved passages are returned when the language model is unavailable
If retrieval finds passages but the chat model request fails for any reason, such as an error, a rate limit or a used-up quota, `/answer` SHALL still respond 200. The answer text SHALL be built from the retrieved passages, and it MUST NOT include the provider's error details.

#### Scenario: Free-tier quota exhausted
- **GIVEN** retrieval returns passages `returns#1` and `shipping#1`
- **WHEN** the chat model request fails with a rate-limit error
- **THEN** `/answer` returns 200, its text says a generated answer is unavailable and lists each passage's text labelled with its chunk id, and `citations` is `["returns#1", "shipping#1"]`

#### Scenario: Provider error text is not exposed
- **WHEN** the chat model request fails with an error message containing provider details
- **THEN** that error message does not appear anywhere in the `/answer` response

### Requirement: Failures before the language model is called return a generic answer
If answering fails before the chat model is called, for example because the question can't be embedded, `/answer` SHALL respond 200 with a fixed message asking the user to try again, with no citations. It MUST NOT include the provider's error details.

#### Scenario: Embedding quota exhausted
- **WHEN** embedding the question fails with a rate-limit error whose message contains provider details
- **THEN** `/answer` returns 200 with text saying the knowledge base can't be searched right now, `citations` is empty, `debug.answer_mode` is `error`, and the provider's message appears nowhere in the response

### Requirement: Response reports how the answer was produced
The `/answer` response SHALL include `debug.answer_mode`. Its value is `generated` when the language model produced the answer, `extractive` when the answer was built from retrieved passages, `no_results` when retrieval found nothing, and `error` when answering failed before the language model was called.

#### Scenario: Model answered
- **WHEN** retrieval finds passages and the chat model returns an answer
- **THEN** `debug.answer_mode` is `generated`

#### Scenario: Fallback answer
- **WHEN** retrieval finds passages and the chat model request fails
- **THEN** `debug.answer_mode` is `extractive`

#### Scenario: Nothing retrieved
- **WHEN** retrieval finds no passages
- **THEN** the chat model is not called, the existing "don't have enough information" answer is returned with no citations, and `debug.answer_mode` is `no_results`
