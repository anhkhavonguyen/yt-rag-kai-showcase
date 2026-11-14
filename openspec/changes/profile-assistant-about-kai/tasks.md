# Tasks

**Build approach (design decision 11).** Implement with Claude Code directly. Don't run the agent orchestrator (`python -m orchestrator`) for this change: its agents use the free Gemini quota, which is kept for the owner's own testing. Nothing in groups 1–6 calls a model:
- tests use the fakes in `tests/conftest.py`;
- `verify_rag.py` and `test_setup.py` are edited but not run, because they call the real services;
- local browser checks look at layout and focus only. Don't send a question or click a sample question locally, because each one is a Gemini call.

**Branch.** Implement on a new branch, `profile-assistant-about-kai`. Branch from `main` once `dark-theme-admin-sign-in-via-agents` is merged, or from that branch until then. This change edits the dark-theme pages and their tests.

## 1. Profile documents (spec: profile-assistant)

- [x] 1.1 Create the branch and check the baseline. Verify: `pytest` and `ruff check .` pass before any edits.
- [x] 1.2 Replace `DEFAULT_DOCUMENTS` in `app/data/default_documents.py` with the ten documents in design.md's "Document drafts". Each has its `chunk_id`, `title`, `source` (`https://www.linkedin.com/in/khavo2907/`) and `text`. Add `DOCUMENT_TITLES`, built from the list and keyed by `chunk_id`. Update the module docstring to say the documents describe Kha Vo (Kai). Verify: `python -c "from app.data.default_documents import DOCUMENT_TITLES as t; print(t)"` prints the ten IDs with the titles from design decision 1.
- [x] 1.3 Add `tests/test_default_documents.py` with these checks:
  - the ID set is exactly the ten IDs, with no duplicates;
  - every `title` is non-empty and unique;
  - every `source` is the LinkedIn URL;
  - every text contains "Kai" or "Kha Vo";
  - `kai_overview_v1` says Kha Vo goes by Kai;
  - each document makes exactly one chunk with the default `TextChunker`;
  - no text matches "return policy", "shipping", "sizing" or "customer support";
  - no text matches "profile views", "impressions", "search appearances", "followers", "connections" or "Etown";
  - no text matches an email-address pattern, a phone-number pattern or the credential-ID shape (a 12-character lowercase-letter-and-digit token that contains digits).

  Verify: `pytest tests/test_default_documents.py` passes, and fails if a test document with an email address is added.
- [x] 1.4 Read the ten texts in the code against design.md and the pasted profile. Check two things: every fact appears on the profile, and no person other than Kha Vo is named (decision 2: this is checked by review, not by a name denylist). Verify: the reviewer notes "documents reviewed" in the PR description.

## 2. Replace-on-seed (spec: knowledge-base-seeding)

- [x] 2.1 In `app/core/database.py`, add `delete_chunks_except(keep_chunk_ids) -> int`, following design decision 4:
  - page through `id, chunk_id` with `.range()` in pages of 1000;
  - delete stale rows by `id` with `.in_("id", batch)` in batches of 100;
  - return the number deleted;
  - make no delete call when nothing is stale.

  Add `tests/test_database.py` with a stub Supabase client. Cover these cases:
  - 1,050 rows over two pages;
  - stale IDs deleted in batches of at most 100;
  - chunk IDs containing `#`, `,` and `(` are kept or deleted correctly;
  - the returned count;
  - no delete call when everything is kept.

  Verify: `pytest tests/test_database.py` passes.
- [x] 2.2 Change `RAGService.seed_documents` in `app/services/rag.py` to return `inserted` and `removed`:
  - if there are no chunks, return `0, 0` before embedding;
  - otherwise embed, upsert, then call `delete_chunks_except` with the seeded chunk IDs.

  Extend `FakeDatabase` in `tests/conftest.py` with:
  - a `stored` dict keyed by chunk ID, which `upsert_chunks` writes;
  - `delete_chunks_except`;
  - a log of call order;
  - switches that make the upsert or the delete fail.

  In `tests/test_rag_service.py`, update the existing seed tests and add one for each `knowledge-base-seeding` scenario:
  - the old store chunks are removed (`removed == 4`);
  - a document gets shorter;
  - seeding the same documents again gives `removed == 0`;
  - embedding fails, and nothing is deleted;
  - saving fails, and nothing is deleted;
  - deleting fails: the error is raised and the new chunks stay;
  - only blank documents: no embedding and no database calls.

  Verify: `pytest` passes.
- [x] 2.3 Add `removed: int` to `SeedResponse` in `app/models/responses.py`. Make `/seed` in `app/main.py` return `inserted` and `removed`, and change its docstring from "policy/FAQ documents" to "profile documents". In `tests/test_api.py`, add tests:
  - the `/seed` body has integer `inserted` and `removed`;
  - `{"docs": []}` calls `seed_documents` with `None`.

  Keep the existing 401 tests, which assert that `seed_documents` is never awaited. Verify: `pytest` passes.
- [x] 2.4 Update the save messages:
  - `static/admin.html`: after a save, show "✅ Saved N chunks, removed M old ones" from `data.inserted` and `data.removed`;
  - `chatbot.py`: after `/seed`, print both numbers, in both the Rich and the plain output.

  Add a test in `tests/test_theme.py` that the admin page's source uses `data.removed` in its save message. Verify: `pytest` passes. The message itself is checked in the browser in 7.2.
- [x] 2.5 Document replace-on-seed:
  - `README.md`: the `/seed` section and its response example;
  - `DEPLOYMENT.md`: the seeding section.

  Say that a seed replaces the whole knowledge base, and that the response includes `removed`. Verify: the documented `curl` for `/seed` matches the new response shape.

## 3. Answer sources (spec: question-answering)

- [x] 3.1 In `RAGService.answer_query` (`app/services/rag.py`), add `sources` to every result, following design decision 5:
  - one `{chunk_id, title, text}` per citation, in citation order, built from the context blocks;
  - the title comes from `DOCUMENT_TITLES` by the chunk ID's part before `#`, falling back to the chunk ID;
  - `[]` for `no_results` and `error`.

  In `tests/test_rag_service.py`, add tests:
  - a generated answer citing one of two context chunks gives one source with its title and passage;
  - an extractive answer gives one source per context chunk, in order;
  - a chunk from an unknown document gets its chunk ID as the title;
  - `no_results` and `error` give `[]`.

  Verify: `pytest` passes.
- [x] 3.2 Add a `Source` model (`chunk_id`, `title`, `text`) and `AnswerResponse.sources`, defaulting to `[]`, in `app/models/responses.py`. Make `/answer` in `app/main.py` pass `sources` through. In `tests/test_api.py`:
  - make the mocked RAG results include `sources`;
  - add a test that the `/answer` body carries them unchanged.

  Add `sources` to the README's `/answer` response example. Verify: `pytest` passes.

## 4. Assistant prompt (spec: profile-assistant)

- [x] 4.1 Move the system prompt in `app/services/chat.py` into the module constant `SYSTEM_PROMPT`, with the text from design decision 3, as plain lines without the current indentation. Use it for both providers. In `tests/test_chat_service.py`, add these tests:
  - the OpenAI-style client receives `SYSTEM_PROMPT` as its system message;
  - the Anthropic-style client receives it as `system=`;
  - `SYSTEM_PROMPT` contains "Kai", "Kha Vo", "third person" and `https://www.linkedin.com/in/khavo2907/`;
  - it contains none of "returns", "shipping", "sizing" or "customer support".

  Switch the file's sample context and questions to profile wording. Verify: `pytest` passes.

## 5. Showcase chat page (specs: profile-assistant, ui-theme)

- [x] 5.1 Add color tokens to `static/theme.css` for the profile panel, skill tags, sample-question buttons, and source list and mode line. Add each new text and background pair to the contrast checks in `tests/test_theme.py`. Verify: `pytest` passes, with every new text pair at least 4.5:1 and every new button background at least 3:1 against the page.
- [x] 5.2 Restructure `static/chat.html` into the profile panel and chat grid from design decision 6. It contains:
  - the profile card;
  - the "Enterprise & cloud" and "AI" skill lists;
  - the four certifications, as text with no verify links until the owner supplies URLs;
  - the LinkedIn link, with `target="_blank"`, `rel="noopener noreferrer"` and hidden "(opens in a new tab)" text;
  - the "Show more" button below 900px, with `aria-controls`, `aria-expanded` and its toggle script;
  - the title, `<h1>`, subtitle and placeholder from design decision 9's wording.

  In `tests/test_theme.py`:
  - rename `test_customer_support_page_keeps_its_content` to `test_chat_page_keeps_its_content`;
  - assert the `<title>` and `<h1>` are "Meet Kai";
  - keep the status, input, Send and `/answer`/`/healthz` assertions;
  - rename `test_customer_support_page_has_no_admin_entry` to `test_chat_page_has_no_admin_entry`;
  - update the module docstring's "Customer Support page" wording.

  Add tests:
  - the panel contains "Kha Vo", "Kai", both skill-group headings and the four certification name lines from design decision 6;
  - each certification name line appears word for word in the `kai_education_certifications_v1` text;
  - every link to another site has `target="_blank"` and a `rel` with `noopener` and `noreferrer`;
  - no link contains `github.com`, and no `href` is empty or `#`;
  - the "Show more" button has `aria-controls` and `aria-expanded="false"`;
  - a `min-width: 900px` media rule exists;
  - the visible text, with `<style>` and `<script>` removed, has none of "Customer Support", "returns", "shipping", "sizing" or "policies".

  Verify:
  - `pytest` passes;
  - in a local browser, without sending a question, the panel is beside the chat at 1280px;
  - at 375px in devtools, the page doesn't scroll sideways, the card above the chat shows only the avatar, name, nickname, headline and LinkedIn link, "Show more" opens and closes and updates its label, and Tab shows a focus ring on the LinkedIn link and "Show more";
  - at 375px with "Show more" opened, the messages list still scrolls inside the chat.
- [x] 5.3 Write the welcome message from design decision 9, with the five sample-question buttons from design decision 7. Wire them to the `sendMessage()` path, and disable them along with Send while an answer is pending. Make `sendMessage` return early while an answer is pending, so Enter in the input can't send a second question. Add tests:
  - the welcome message has five `<button type="button" class="sample-question">`, including "Who is Kai?" and "What can Kai do?";
  - the page script disables `.sample-question` buttons where it disables Send;
  - `sendMessage` checks a pending flag before sending.

  Verify: `pytest` passes, and in a local browser Tab reaches each sample question with a visible focus ring. Don't activate them locally.
- [x] 5.4 Rewrite `addMessage` per design decision 8:
  - every node built with `textContent`, with `white-space: pre-wrap`;
  - citation markers renumbered as `[n]`;
  - one `<details>` per source, with `<summary>` "[n] Title" and the passage in a `<p>`;
  - the mode line, "AI answer" or "Passages only (AI unavailable)", with the response time.

  Pass `data.sources` and `data.debug` from `sendMessage`. Add tests:
  - the chat page's script contains no `innerHTML`;
  - it creates `details` elements;
  - it reads `sources`, `answer_mode` and `latency_ms`;
  - it contains both mode labels.

  Verify: `pytest` passes. The rendered result is checked on the deployed instance in 7.3.
- [x] 5.5 Change the link in `static/admin-login.html` to "← Back to chat". Add a test in `tests/test_theme.py` that the sign-in page links to `/chat` and doesn't contain "Customer Support". Verify: `pytest` passes.

## 6. CLI and examples (spec: profile-assistant)

- [x] 6.1 In `chatbot.py`:
  - add the module constant `EXAMPLE_QUESTIONS` with the five sample questions;
  - use it in the Rich help panel;
  - change the welcome texts (Rich and plain) to "Ask about Kai (Kha Vo): experience, skills and work.".

  Add `tests/test_chatbot.py`: `EXAMPLE_QUESTIONS` includes "Who is Kai?" and "What can Kai do?", and no example mentions returns, shipping, sizing or policies. Verify: `pytest` passes, and `python chatbot.py` then `/help` shows the new examples. `/help` makes no request.
- [x] 6.2 Replace the return-policy example questions in `README.md`, `DEPLOYMENT.md`, `test_setup.py` and `verify_rag.py` with profile questions such as "Who is Kai?" and "What can Kai do?". In the README, the request and response examples use `kai_*` citation IDs. Don't run the two scripts. Verify: `grep -rniE "return policy|shipping|sizing guide|policy_returns" README.md DEPLOYMENT.md test_setup.py verify_rag.py chatbot.py static/ app/` finds nothing.

## 7. Integration and deployed checks

- [ ] 7.1 Run the full local checks. Verify: `pytest`, `ruff check .` and `openspec validate profile-assistant-about-kai --strict` all pass, and CI is green on the PR.
- [ ] 7.2 After the merge to `main` and the Render deploy, follow design.md's Migration Plan, steps 2 and 3:
  - list the table's chunk IDs in the Supabase SQL editor;
  - save from `/admin`. This is one embedding request.

  Verify:
  - the response and the admin message report 10 inserted and 4 removed;
  - the table holds only the ten `kai_*_v1#1` chunks;
  - saving again reports `removed: 0`. This is one more embedding request, and can be skipped to save quota.
- [ ] 7.3 On the deployed `/chat`, ask each of these. Use the sample buttons where they match. The whole list costs about 8 chat and 8 embedding requests.
  - "Who is Kai?"
  - "Who is Kha Vo?"
  - "What can Kai do?"
  - "What does Kai do at DEKRA?"
  - "What salary does Kai expect?"
  - "Can Kai join a call with us next Tuesday?"
  - "What is your return policy?"
  - "Hi"

  For each answer, check:
  - it matches its `profile-assistant` scenario;
  - it refers to Kai by name without guessing pronouns;
  - the sources are listed as "[n] Title" and open to show the passage;
  - Tab reaches each source title with a visible focus ring, and Enter opens it;
  - the citation markers are numbers;
  - the mode line reads "AI answer · n.n s", or "Passages only (AI unavailable)" if the quota has run out;
  - the sample questions and Send are disabled while waiting, and pressing Enter in the input sends nothing.

  On a real phone, check that the short card sits above the chat and "Show more" works. Verify: each answer and whether it passed is recorded in the PR description. Any failure is fixed in the prompt (4.1) or the page (5.x) and rechecked.

## Workflow follow-up

- Archive in this order: `deploy-render-with-gemini`, `move-kb-editor-to-admin-page`, `dark-theme-admin-sign-in-via-agents`, then this change. The `ui-theme` RENAMED and MODIFIED deltas need its main spec to exist; `openspec validate` already reports this.
- After archiving, edit `openspec/specs/ui-theme/spec.md` by hand: change "the Customer Support page" in its Purpose to "the chat page", and rename the scenario "Customer Support on a phone" to "Chat page on a phone".
- When the owner supplies the certificate verify URLs, add a "Verify ↗" link to each certification in `static/chat.html`, with the same `target` and `rel` as the LinkedIn link. No spec or plan change is needed.
