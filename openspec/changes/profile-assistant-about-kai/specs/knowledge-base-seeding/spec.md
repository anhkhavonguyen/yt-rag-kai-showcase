# Spec Delta

## ADDED Requirements

### Requirement: A seed replaces the knowledge base
After a successful `/seed`, the knowledge base SHALL hold exactly the chunks made from that request's documents, or from the default documents when the request has none. Every other chunk SHALL be deleted. Chunks SHALL be deleted only after the new chunks are saved.

#### Scenario: Old store chunks are removed
- **GIVEN** the knowledge base holds `policy_returns_v1#1`, `policy_shipping_v1#1`, `sizing_guide_v1#1` and `support_contact_v1#1`
- **WHEN** `POST /seed` is sent without documents
- **THEN** the knowledge base holds only the default documents' chunks, and the response reports `removed: 4`

#### Scenario: A document gets shorter
- **GIVEN** the knowledge base holds `overview#1` and `overview#2`
- **WHEN** `POST /seed` is sent with a document `overview` whose text fits in one chunk
- **THEN** the knowledge base holds the new `overview#1` and not `overview#2`, and the response reports `removed: 1`

#### Scenario: Seeding the same documents again
- **GIVEN** the knowledge base was just seeded with the default documents
- **WHEN** `POST /seed` is sent without documents again
- **THEN** the knowledge base holds the same chunk IDs with the same text, and the response reports `removed: 0`

#### Scenario: Embedding fails
- **GIVEN** the knowledge base holds chunks
- **WHEN** `POST /seed` is sent and embedding the new chunks fails
- **THEN** the response is 500, and no chunk is added, changed or deleted

#### Scenario: Saving fails
- **GIVEN** the knowledge base holds chunks
- **WHEN** `POST /seed` is sent and saving the new chunks fails
- **THEN** the response is 500, and no chunk is deleted

#### Scenario: Deleting fails
- **WHEN** `POST /seed` saves the new chunks but deleting the other chunks fails
- **THEN** the response is 500, the new chunks stay saved, and sending the same request again deletes the other chunks

### Requirement: A seed that makes no chunks changes nothing
If a `/seed` request's documents produce no chunks, for example because every text is blank, the knowledge base SHALL be left unchanged. No embeddings SHALL be requested, and the response SHALL report `inserted: 0` and `removed: 0`. A request with an empty document list SHALL seed the default documents, as before this change.

#### Scenario: Only blank documents
- **GIVEN** the knowledge base holds chunks
- **WHEN** `POST /seed` is sent with one document whose text is only spaces
- **THEN** the response reports `inserted: 0` and `removed: 0`, no embeddings are requested, and the knowledge base is unchanged

#### Scenario: Empty document list
- **WHEN** `POST /seed` is sent with `{"docs": []}`
- **THEN** the default documents are seeded

### Requirement: The seed response reports removed chunks
The `/seed` response SHALL include `removed`, the number of chunks the seed deleted, next to `inserted`. The admin page's save message and the CLI chatbot's `/seed` message SHALL show both numbers.

#### Scenario: Response fields
- **WHEN** `POST /seed` succeeds
- **THEN** the response body has integer fields `inserted` and `removed`

#### Scenario: Admin page message
- **GIVEN** a signed-in admin on `/admin`
- **WHEN** a save responds `{"inserted": 10, "removed": 4}`
- **THEN** the save message reports 10 chunks saved and 4 removed
