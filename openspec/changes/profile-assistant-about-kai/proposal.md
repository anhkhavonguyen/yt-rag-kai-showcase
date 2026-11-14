# Proposal

## Why

The deployed assistant answers questions about a made-up store's returns, shipping and sizing, which has nothing to do with its owner. The owner, Kha Vo (known as Kai), wants the public chat page to be a showcase instead:
- A recruiter, client or colleague can ask "Who is Kai?" or "What can Kai do?" and get an answer, with sources, drawn from Kai's LinkedIn profile.
- The same page shows Kai's profile, skills and certifications.
- Every answer shows the retrieval-augmented generation (RAG) behind it.

The app already runs on a free public URL, so changing what it knows and how the page presents it is all that's needed.

## What Changes

- **Profile documents replace the policy documents.** The default knowledge base no longer holds the four store documents. It holds ten short, titled documents written from Kai's public LinkedIn profile (https://www.linkedin.com/in/khavo2907/), one per topic:
  - who Kai is;
  - the current DEKRA role at Orient Software;
  - the cloud and production work there;
  - earlier enterprise projects;
  - the DXC role;
  - core expertise;
  - AI focus;
  - education and certifications;
  - career direction;
  - community activity and writing.

  Facts come only from the profile; nothing is invented.
- **What stays out of the knowledge base.** `/documents` is public, so the documents leave out the private parts of the pasted profile:
  - analytics, and follower and connection counts;
  - other people's posts and reposts;
  - other people's names;
  - credential IDs;
  - the office street address.
- **The assistant talks about Kai in the third person.** The system prompt changes from customer support to a profile assistant:
  - "Kai" and "Kha Vo" are treated as the same person;
  - answers use only the knowledge base, with citations;
  - when the profile doesn't cover something, the assistant says so and points to Kai's LinkedIn profile instead of guessing;
  - it never speaks as Kai;
  - questions that aren't about Kai are steered back politely.
- **BREAKING: seeding replaces the knowledge base.**
  - **Today:** `/seed` only adds or updates chunks, so the old policy chunks would stay in the deployed database and keep turning up in answers.
  - **After this change:** a successful seed leaves exactly the seeded chunks. Every other chunk is deleted, and only after the new ones are saved.
  - **Response:** the `/seed` response adds a `removed` count.
  - **No chunks:** seeding documents that produce no chunks changes nothing.
  - **Who this breaks:** anyone who used `/seed` to add a few documents next to the defaults now replaces the defaults instead.
- **The chat page becomes Kai's showcase.** `/chat` is titled "Meet Kai".
  - **Sidebar:**
    - a profile card: name and nickname, headline, Ho Chi Minh City, 12+ years, current role, and a link to the LinkedIn profile;
    - skills shown as tags in two groups, "Enterprise & cloud" and "AI";
    - four certifications: Claude Code in Action, AWS Educate Machine Learning Foundations, OCI 2025 Certified AI Foundations Associate, and Microsoft Certified Professional (Programming in C#). Each links to its public verification page once its URL is supplied.
  - **Chat:** opens with clickable sample questions. Under each answer it lists the sources, each title opening to show its passage, plus how the answer was made ("AI answer", or "Passages only (AI unavailable)") and the response time.
  - **On a phone:** a short profile card sits above the chat, and the rest is behind "Show more".
  - **Plain text:** questions and answers are shown as plain text, never as HTML.
  - **Left out:** no GitHub link, and no "how it's built" panel.
- **`/answer` lists its sources.** The response adds `sources`: the chunk ID, title and passage for each citation. The field is additive.
- **Other wording.**
  - The sign-in page's "Back to Customer Support" link becomes "Back to chat".
  - The admin page's save message reports removed chunks.
  - The CLI chatbot's welcome text and example questions are about Kai.
- **Docs and examples.** The README, `DEPLOYMENT.md`, `test_setup.py` and `verify_rag.py` use profile questions instead of return-policy questions.

## Capabilities

### New Capabilities
- `profile-assistant`: what the assistant knows and how it answers, and how `/chat` and the CLI present it. Covers:
  - the default knowledge base about Kha Vo (Kai), and what it leaves out;
  - the third-person voice, grounded answers, and how gaps are handled;
  - the showcase chat page: the profile panel, skills, certifications, sample questions and answer details.

### Modified Capabilities
- `knowledge-base-seeding`: adds the rule that a seed replaces the knowledge base, and the `removed` count in the response. The admin-token rules don't change.
  - This capability is introduced by `deploy-render-with-gemini`.
  - It is modified by `move-kb-editor-to-admin-page` and `dark-theme-admin-sign-in-via-agents`.
  - None of these changes is archived yet.
- `question-answering`: adds `sources` to the `/answer` response. The answer modes and fallbacks don't change. This capability is introduced by `deploy-render-with-gemini`, which isn't archived yet.
- `ui-theme`: the requirement "The Customer Support page keeps its content and behavior" pins the "Customer Support" title, subtitle and welcome message. It is renamed and changed so the dark theme still can't change the page's content, but the content is now the profile assistant's showcase. This capability is introduced by `dark-theme-admin-sign-in-via-agents`, which isn't archived yet.

## Impact

- **Code**:
  - `app/data/default_documents.py`: new documents with titles.
  - `app/services/chat.py`: new system prompt.
  - `app/services/rag.py` and `app/core/database.py`: replace-on-seed, the removed count, and answer sources.
  - `app/models/responses.py` and `app/main.py`: `removed` in the `/seed` response, `sources` in the `/answer` response, and docstrings.
  - `static/chat.html`: rewritten as the showcase page.
  - `static/theme.css`: new color tokens for the sidebar, tags and sources.
  - `static/admin-login.html`, `static/admin.html` and `chatbot.py`: wording.
- **API**:
  - `/seed` deletes chunks that weren't in the request (**BREAKING**, see above), and adds `removed` to its response (additive).
  - `/answer` adds `sources` (additive).
  - `/documents` returns the profile documents, which now include a `title`.
- **Data**: the schema is unchanged. After deploying, the owner runs one seed from `/admin` or the CLI. It embeds ten chunks, which is one embedding request on the free Gemini tier, and deletes the four policy chunks (`removed: 4`).
- **Tests**:
  - `tests/test_theme.py`: its "Customer Support" content checks change to the new page. It gains checks for the sidebar, links, sample questions, plain-text rendering and the new colors' contrast.
  - New tests cover replace-on-seed, answer sources, the default documents and the prompt's rules.
  - All tests run in the existing CI with fakes, so no keys are needed.
- **Model usage**: the change is built directly with Claude Code, not with the project's agent orchestrator. Implementation and tests make no Gemini calls. The free Gemini quota is kept for the one seed and the owner's own checks after deploying.
- **Dependencies**: none added.
- **Depends on**: `dark-theme-admin-sign-in-via-agents` (the current branch). Its `ui-theme` and `knowledge-base-seeding` deltas are the ones this change modifies, so it should be merged first.
