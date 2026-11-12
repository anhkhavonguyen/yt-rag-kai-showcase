# Spec Delta

## Purpose

Sets which OpenAI-compatible endpoint and which models the application uses for chat answers and text embeddings. A free provider can replace OpenAI through configuration alone, and every embedding fits the vector store's fixed size.

## ADDED Requirements

### Requirement: Endpoint is configurable for chat and embeddings
When `AI_PROVIDER` is `openai`, the system SHALL send both chat and embedding requests to the endpoint in the `OPENAI_BASE_URL` setting, authenticated with `OPENAI_API_KEY`. When `OPENAI_BASE_URL` is unset, it SHALL use the default OpenAI endpoint.

#### Scenario: Free OpenAI-compatible provider configured
- **GIVEN** `OPENAI_BASE_URL` is set to `https://generativelanguage.googleapis.com/v1beta/openai/` and `OPENAI_API_KEY` holds a Gemini API key
- **WHEN** the system embeds a document or generates an answer
- **THEN** the request is sent to that base URL with that key, and no request goes to api.openai.com

#### Scenario: No base URL configured
- **GIVEN** `OPENAI_BASE_URL` is not set
- **WHEN** the system embeds a document or generates an answer
- **THEN** the request goes to the default OpenAI endpoint, as before this change

### Requirement: Model names are configurable
The system SHALL use the chat model named by `OPENAI_CHAT_MODEL` and the embedding model named by `OPENAI_EMBED_MODEL` for every request, with no provider-specific model hardcoded.

#### Scenario: Gemini models configured
- **GIVEN** `OPENAI_CHAT_MODEL=gemini-3.5-flash` and `OPENAI_EMBED_MODEL=gemini-embedding-2`
- **WHEN** an answer is generated and a query is embedded
- **THEN** the chat request names `gemini-3.5-flash` and the embedding request names `gemini-embedding-2`

### Requirement: Embeddings have the configured size
Every embedding the system stores or uses for search SHALL have exactly `EMBEDDING_DIMENSIONS` values (default 1536), whatever size the provider returns by default.

#### Scenario: Provider returns the requested size
- **WHEN** the provider returns embeddings with exactly `EMBEDDING_DIMENSIONS` values
- **THEN** the system uses them unchanged

#### Scenario: Provider returns a longer embedding
- **GIVEN** `EMBEDDING_DIMENSIONS` is 1536
- **WHEN** the provider returns a 3072-value embedding
- **THEN** the system keeps the first 1536 values, rescales the result to unit length, and stores or searches with that 1536-value vector

#### Scenario: Provider returns a shorter embedding
- **GIVEN** `EMBEDDING_DIMENSIONS` is 1536
- **WHEN** the provider returns an embedding with fewer than 1536 values
- **THEN** the operation fails with an error stating the expected and actual sizes, and nothing is written to the knowledge base

### Requirement: Embedding requests are batched
The system SHALL send at most `EMBEDDING_BATCH_SIZE` texts (default 100) in one embedding request, and SHALL return embeddings in the same order as the input texts.

#### Scenario: More texts than one batch
- **GIVEN** `EMBEDDING_BATCH_SIZE` is 100
- **WHEN** 250 chunks are seeded
- **THEN** the system makes 3 embedding requests of 100, 100 and 50 texts, and chunk *n* is stored with the embedding of text *n*
