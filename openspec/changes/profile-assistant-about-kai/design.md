# Design

## Context

- **Default documents.** `app/data/default_documents.py` holds four store documents: `policy_returns_v1`, `policy_shipping_v1`, `sizing_guide_v1` and `support_contact_v1`.
  - `/documents` returns them, and the endpoint is public with no auth.
  - `/seed` without documents stores them.
  - The admin page loads `/documents` and saves every document through `/seed`.
  - `DocumentChunk` (the `/seed` request model) ignores fields it doesn't declare.
- **Chunking.** `TextChunker` splits by words: `chunk_size` 400 tokens is about 300 words, with 45 words of overlap. A shorter document becomes one chunk, `<chunk_id>#1`.
- **Seeding.**
  - `RAGService.seed_documents` chunks, embeds every chunk in one batch, then calls `db.upsert_chunks`, which upserts on `chunk_id`.
  - Nothing is ever deleted. The deployed Supabase table therefore still holds the four policy chunks, and they would keep coming back in answers after a profile seed.
  - `seed_documents` returns the upserted count, and `/seed` returns `{"inserted": n}`.
  - `SeedRequest.docs = []` is falsy, so an empty list already seeds the defaults.
- **Retrieval.**
  - `match_chunks` returns the top `top_k` chunks (default 6) with no similarity floor.
  - `_prepare_context` keeps one chunk per document, at most 4. So every question, including an off-topic one, reaches the model with up to four profile passages. Steering off-topic questions is the prompt's job.
- **Answering.**
  - `ChatService.generate_answer` uses an inline customer-support system prompt. The user prompt wraps the context as `[chunk_id] text` and asks for citations.
  - `RAGService._extract_citations` keeps only `[id]`s that were in the context.
  - `/answer` returns `text`, `citations` (chunk IDs) and `debug` (`top_doc_ids`, `latency_ms`, `answer_mode`).
  - When the model fails, the answer is the passages verbatim (`extractive`), and `citations` lists every context chunk.
- **Chat page.**
  - `static/chat.html` is one hand-written page with inline CSS and JS and no build step.
  - Its heading is "Customer Support", and its subtitle, welcome text and placeholder are about policies.
  - `addMessage` sets `contentDiv.innerHTML = content.replace(/\n/g, '<br>')`, so the answer and the visitor's own question are inserted as HTML.
  - Citations show as "📚 Sources: <chunk ids>".
  - The page ignores `debug`.
- **Theme rules (from the in-flight `ui-theme` capability, checked by `tests/test_theme.py`).**
  - Every color is a token in `static/theme.css`, and page styles hold no hex values.
  - Text has at least 4.5:1 contrast, and buttons and the focus ring at least 3:1.
  - Every link, button and input shows a visible focus.
  - Pages work 375 pixels wide without sideways scrolling.
  - Nothing is loaded from another origin.
  - `/chat` has no link to `/admin`.
- **Other pages and the CLI.**
  - `static/admin-login.html` links "← Back to Customer Support".
  - `static/admin.html` shows "Successfully updated N documents" after a save.
  - `chatbot.py` has policy examples and prints `inserted` after `/seed`.
- **Tests.**
  - `tests/conftest.py` provides `FakeDatabase`, with `upserted` and `search_results`, and fakes for embeddings and chat. It also blocks real Supabase and model calls.
  - There are no browser or JS tests. Page tests parse the served HTML and CSS.
- **Model quota.** The free Gemini quota is limited. The project's agent orchestrator (`orchestrator/`), which built the dark-theme change, makes many model calls per run.
- **In-flight changes.** `dark-theme-admin-sign-in-via-agents` is the current branch and isn't archived. It owns the `ui-theme` delta and the latest `knowledge-base-seeding` delta. `deploy-render-with-gemini` introduces `question-answering`. `openspec/specs/` is empty.

## Goals / Non-Goals

**Goals:**
- Ten short, titled, self-contained profile documents, one chunk each, whose facts all come from the pasted LinkedIn profile.
- A seed that leaves the knowledge base equal to what was seeded, without ever passing through an empty or half-deleted state when embedding or saving fails.
- A chat page that works as Kai's showcase:
  - profile, skills and certifications beside the chat;
  - sample questions to start with;
  - every answer showing its sources and how it was made.
- Tests that pin the document rules, the prompt's rules and the page's structure without a real model.

**Non-Goals:**
- **Persisting admin-page edits across reloads.** The page still loads the defaults from code. That's existing behavior.
- **Retrieval changes.** No similarity threshold and no re-ranking.
- **Other languages.** No answering in languages other than English, and no detecting who the visitor is.
- **Unchanged pieces.** No change to `/answer`'s existing fields, the fallback texts, or the admin-token rules.
- **A database migration.** The schema and `match_chunks` stay as they are. Titles live in code, not in the table.
- **Excluded by the owner:**
  - a GitHub link;
  - a "how it's built" panel;
  - a document about this RAG app itself.
- **A photo.** None was provided, and loading one from LinkedIn would break the no-other-origins rule. The card shows initials.
- **Clickable links inside answer text.** Answers are plain text. The LinkedIn link lives in the profile panel.
- **A JavaScript test framework.** Rendering is checked by reading the page source and by hand in the browser.

## Decisions

### 1. Ten titled topic documents, one chunk each, written in the third person by name
- **What:** replace `DEFAULT_DOCUMENTS` with the ten documents drafted at the end of this design. Each one:
  - has a `chunk_id`, a `title`, a `source` and its `text`;
  - keeps to about 250 words, under the roughly 300-word chunk limit, so it becomes exactly one chunk and its citation names one topic;
  - starts by naming "Kha Vo (Kai)" or "Kai (Kha Vo)", so it matches searches for either name and reads correctly as a lone passage in `extractive` mode;
  - refers to Kai by name, never by pronoun;
  - anchors facts that age to dates, such as "since July 2016" and "12+ years as of 2026", instead of relative ages like "10 years at Orient".
- **IDs:** `kai_<topic>_v1`, following the existing `_v1` style.
- **`source`:** the profile URL, `https://www.linkedin.com/in/khavo2907/`, for all ten.
- **`title`:** shown to visitors as the source name, so it is short and plain. It is not stored in the database. `DocumentChunk` ignores it when the admin page sends documents back.

  | ID | Title |
  |---|---|
  | `kai_overview_v1` | Who Kai is |
  | `kai_current_role_v1` | Current role: DEKRA booking platform |
  | `kai_cloud_production_v1` | Azure and production work |
  | `kai_earlier_projects_v1` | Other enterprise projects |
  | `kai_dxc_v1` | DXC Technology Vietnam (2014–2016) |
  | `kai_expertise_v1` | Core expertise |
  | `kai_ai_focus_v1` | AI focus |
  | `kai_education_certifications_v1` | Education and certifications |
  | `kai_career_direction_v1` | Career direction |
  | `kai_community_writing_v1` | Writing and community |

- **Why:** narrow documents retrieve precisely. "What does Kai do at DEKRA?" pulls the current-role and cloud documents, not a long résumé chunk that dilutes the context. One chunk per document also means `_prepare_context`'s four-document cap gives the model four distinct topics, and each source the visitor sees is one clear topic.
- **Rejected:**
  - One long résumé document. It would chunk mid-topic and give vague sources.
  - First-person text copied from the "About" section. It would read as Kai speaking in fallback answers.

### 2. What is left out of the documents
- **Left out:**
  - analytics (profile views, impressions, search appearances), and follower and connection counts;
  - other people's posts and reposts. Of the ADLC post Kai shared, only Kai's interest in the topic is kept;
  - everyone's names except Kai's: speakers, colleagues, and the colleague who thanked Kai;
  - credential IDs;
  - the office street address. Only "Ho Chi Minh City" is kept.
- **Kept:** the LinkedIn profile URL, which the owner supplied for this purpose.
- **Why:** `/documents` is public and the documents ship in the repo, so they must hold nothing beyond what Kai would show a stranger. Other people never agreed to appear in Kai's chatbot.
- **Verify links are separate.** The page's certificate verify links point to public verification pages, and only links the owner supplies are added. They live in the page, not in the knowledge base.
- **Checked by tests where possible:**
  - patterns for email addresses, phone numbers and the credential-ID shape;
  - words such as "profile views", "impressions", "followers", "connections" and "Etown".
- **Checked by review only:** "no other people's names". A test with a denylist of the people named in the pasted profile would itself put their names in the repo.

### 3. A new system prompt, held in a module constant
- **What:** move the prompt into `SYSTEM_PROMPT` in `app/services/chat.py`. The user prompt template stays the same.
- **Draft prompt:**

  ```text
  You are the assistant on Kha Vo's profile page. Kha Vo goes by Kai. Visitors such as
  recruiters, clients and colleagues ask you about Kai.

  Rules:
  1. "Kai" and "Kha Vo" are the same person. Talk about Kai in the third person, by name.
  2. You are not Kai. Never write as Kai. Never accept offers, agree to meetings, or state
     Kai's availability or rates; suggest contacting Kai on LinkedIn
     (https://www.linkedin.com/in/khavo2907/) instead.
  3. Answer questions about Kai only from the context. Cite every passage you use with its
     [chunk_id].
  4. If the context doesn't answer the question, say Kai's profile doesn't cover it and
     suggest contacting Kai on LinkedIn (https://www.linkedin.com/in/khavo2907/). Never
     guess or add facts.
  5. If a question isn't about Kai, say briefly that you answer questions about Kai and
     suggest one, such as "What can Kai do?". Don't answer it from general knowledge.
  6. Reply to greetings briefly and offer to help.
  7. Write plain text without Markdown: no **, # or backticks. For a list, start each item
     on its own line with "- ".
  8. Be concise, friendly and professional.
  ```

  Rule 7 exists because the chat page shows answers as plain text (decision 8). Without it, Gemini's Markdown would show up as literal `**` and `#`.

  The prompt is written as plain lines, without the current deep indentation that gets sent to the model.
- **Why a constant:** tests can assert on the prompt's rules without capturing provider calls, and the Anthropic path uses the same text.
- **Rejected:** putting the persona rules into a seeded "instructions" document. Retrieval might not return it, and an admin edit could silently change the assistant's behavior.

### 4. Replace-on-seed: save first, then delete everything not seeded, by row ID
- **Order in `RAGService.seed_documents`:**
  1. Chunk the documents. If there are no chunks, return `inserted=0, removed=0` with no embedding or database call.
  2. Embed the chunks.
  3. Upsert them. This is the current code.
  4. Call `db.delete_chunks_except(seeded_chunk_ids)`. It returns how many rows it deleted.
- **Return value:** `seed_documents` returns a small result with `inserted` and `removed`, replacing the bare int. `/seed` passes both through, and `SeedResponse` gains `removed: int`.
- **`delete_chunks_except`:**
  - reads `id, chunk_id` from `rag_chunks` in pages of 1000 using `.range()`, because PostgREST caps unpaged reads at 1000 rows;
  - works out which row IDs are stale in Python;
  - deletes them with `.in_("id", batch)` in batches of 100.
- **Why delete by row ID and not by chunk ID:** chunk IDs contain `#` and may contain `,` or `(`. Those characters are special in PostgREST's `in.(…)` filter, and `/seed` accepts any chunk ID. Integer IDs need no quoting.
- **Why this order:** if embedding or saving fails, nothing has been deleted, and the old knowledge base keeps answering. If deleting fails, the new chunks are already in place, and re-sending the same seed finishes the cleanup, because the delete step is idempotent.
- **Rejected:**
  - Delete everything, then insert. A failed embedding call, which is likely on the free Gemini quota, would leave the knowledge base empty.
  - A `replace=true` flag on `/seed`. The CLI's default seed would keep the stale-chunk trap, and the owner chose replacement as the rule.
  - An SQL function that upserts and deletes in one transaction. It's atomic, but it needs a manual schema change on the owner's Supabase project, and the app has no migration tooling.

### 5. `/answer` builds `sources` on the server
- **What:** after `_extract_citations`, `RAGService.answer_query` builds `sources` from the context blocks it already holds: `{chunk_id, title, text}` for each citation, in citation order.
- **Titles:** looked up by the part of the chunk ID before `#`, in `DOCUMENT_TITLES`. That map is built in `default_documents.py` from `DEFAULT_DOCUMENTS`. A chunk whose document has no title gets its chunk ID as the title.
- **By answer mode:**
  - `extractive` answers already cite every context chunk, so all of them become sources;
  - `no_results` and `error` give `[]`.
- **Response model:** `AnswerResponse` gains `sources: List[Source]`, defaulting to `[]`. `main.py` passes it through.
- **Why the server:** the server holds the exact passages the answer was built from, so the page shows what the model actually saw. That's the point of the transparency.
- **Rejected:**
  - Looking up titles and passages in the page from `/documents`. `/documents` returns the defaults from code, which can differ from the database after an admin edit, and it costs an extra request.
  - A `title` column in `rag_chunks`. It needs a manual migration for a label.

### 6. Chat page layout: profile panel beside the chat, collapsing on a phone
- **Structure:** `.app-container` becomes a CSS grid with two children:
  - `<aside class="profile-panel" aria-label="About Kai">`;
  - the existing `.chat-section`.

  At `min-width: 900px` the grid is `320px 1fr`. Narrower, it is one column with the aside first.
- **Size:** `.app-container`'s `max-width` grows from 900px to 1200px, so the chat keeps its current width beside the panel.
  - From 900px up, the container keeps its fixed height (90vh), and the profile panel scrolls on its own (`overflow-y: auto`).
  - Below 900px, the container's height becomes `auto` and the page scrolls. `.chat-section` gets its own height (80vh), so the messages still scroll inside the chat however tall the panel is.
- **Profile card**, always shown:
  - an initials avatar, "KV", as text;
  - "Kha Vo", with "Known as Kai";
  - the headline;
  - a "LinkedIn ↗" link to `https://www.linkedin.com/in/khavo2907/`.
- **Details** (`<div id="profile-more">`), below the card:
  - "Ho Chi Minh City, Vietnam · 12+ years";
  - "Team Lead, Orient Software · DEKRA Global Vehicle Inspection Booking";
  - the skills and certifications below.
- **Skills:** two `<ul>` tag lists under the headings "Enterprise & cloud" and "AI". Tags are list items, not buttons, because they do nothing.
  - **Enterprise & cloud:** C#, .NET, ASP.NET Core, Angular, TypeScript, SQL Server, REST APIs, Microsoft Azure, API Management, Azure Cache for Redis, Multi-tenant architecture, Distributed systems.
  - **AI:** LLMs, RAG, AI agents, Tool calling, Agentic development, Claude Code, GitHub Copilot.
- **Certifications:** a `<ul>`. Each item has a name line and, below it, a detail line:
  - "Claude Code in Action", then "Anthropic · Mar 2026";
  - "AWS Educate Machine Learning Foundations", then "Amazon Web Services · Jul 2025";
  - "Oracle Cloud Infrastructure 2025 Certified AI Foundations Associate", then "Oracle · 2025";
  - "Microsoft Certified Professional", then "Programming in C# · Microsoft". There's no date on the profile.

  Each name line matches the name in `kai_education_certifications_v1` word for word, so the page test can match them. An item gets a "Verify ↗" link only when the owner has supplied its URL. Until then, it has no link at all. Adding one later is a one-line HTML edit.
- **Links to other sites:** `target="_blank" rel="noopener noreferrer"`, plus visually hidden text "(opens in a new tab)".
- **Phone:**
  - Below 900px, `#profile-more` (location, role, skills and certifications) is hidden unless the panel has the class `expanded`. The card above the chat stays short: avatar, name, nickname, headline and LinkedIn link.
  - A `<button type="button" aria-controls="profile-more" aria-expanded="false">Show more</button>` toggles that class, its label ("Show less") and `aria-expanded`.
  - From 900px up, the button is hidden and `#profile-more` is always shown.
- **Colors:** new tokens in `static/theme.css` for the panel, tags, sample-question buttons and source list. Each text and background pair is added to the contrast checks in `tests/test_theme.py`. Page styles reference only `var(--…)`.
- **Why a sidebar:** both the proof and the chat are visible at once on a desktop, which is how recruiters usually look. On a phone, the chat stays usable without scrolling past the profile.
- **Rejected:** a header card with tabs. It hides the proof while chatting, and the owner chose the sidebar.

### 7. Sample questions are buttons that go through the Send path
- **What:** the welcome message holds five `<button type="button" class="sample-question">` elements:
  - "Who is Kai?"
  - "What can Kai do?"
  - "What is Kai working on now?"
  - "What AI experience does Kai have?"
  - "Which certifications does Kai have?"
- **Behavior:**
  - Activating one puts its text in the input and calls the existing `sendMessage()`, so typed and clicked questions behave identically.
  - `sendMessage` disables Send and every `.sample-question` until the answer arrives.
  - `sendMessage` returns at once while an answer is pending. Today the input's Enter handler calls it directly, even while Send is disabled, so without this check Enter could send a second question.
- **Why:** native buttons work with the keyboard and screen readers without extra code. While an answer is pending, disabling the buttons and returning early stop double clicks and repeated Enter presses from spending a second model call.

### 8. Answers render as plain text with numbered, expandable sources
- **Plain text:**
  - `addMessage` builds every node with `textContent`. CSS `white-space: pre-wrap` keeps line breaks.
  - The chat page's script contains no `innerHTML`.
  - The visitor's own question gets the same treatment.
- **Citation markers:** for a bot answer, each `[chunk_id]` in the text that matches an entry in `sources` is replaced by `[n]`, its 1-based position in `sources`. Markers that don't match are left as written.
- **Sources:** under the answer, a "Sources" label and one `<details>` per source:
  - the `<summary>` is "[n] Title";
  - the body is a `<p>` with the passage text.

  Native `<details>` opens with a click, Enter or Space, and screen readers announce whether it is open.
- **Mode line:**
  - `generated` shows "AI answer";
  - `extractive` shows "Passages only (AI unavailable)";
  - `no_results` and `error` show no line;
  - the time is `(latency_ms / 1000).toFixed(1) + " s"`, joined with " · ".
- **Why:** the answer details are the visible proof that the RAG pipeline works. "Passages only" also tells the owner, and a visitor, when the free quota has run out. Using `textContent` closes the existing HTML-injection gap at no cost while the function is being rewritten anyway.

### 9. Wording
- **`static/chat.html`:**
  - `<title>` and `<h1>`: "Meet Kai".
  - Subtitle: "Ask about Kha Vo's experience, skills and work".
  - Welcome message: "Hi! 👋 I answer questions about Kha Vo, known as Kai, using Kai's LinkedIn profile. Try asking:", followed by the five sample-question buttons (decision 7).
  - Input placeholder: "Ask a question about Kai...".
- **`static/admin-login.html`:** "← Back to chat".
- **`static/admin.html`:** after a save, "✅ Saved N chunks, removed M old ones".
- **`chatbot.py`:**
  - welcome text: "Ask about Kai (Kha Vo): experience, skills and work.";
  - help examples: the five sample questions, held in a module constant `EXAMPLE_QUESTIONS`;
  - `/seed` message: shows `inserted` and `removed`.
- **The "no store wording" test:** checks the page's visible text, with `<style>` and `<script>` removed. Otherwise the CSS `box-sizing` would match "sizing".

### 10. Verification without a real model
- **Unit tests, with the existing fakes:**
  - the document rules: the ten IDs, unique titles, each document naming Kai, the nickname stated, one chunk each, and the content left out;
  - `SYSTEM_PROMPT`'s rules;
  - replace-on-seed and its failure orders;
  - `delete_chunks_except` paging and batching;
  - `sources` in the RAG result and in `/answer`;
  - the `/seed` response;
  - the CLI examples.
- **Page tests, which parse the served `/chat` HTML:**
  - the title and heading;
  - the profile-panel content and link attributes;
  - no GitHub link, and no empty or `#` links;
  - each certification on the page also named in `kai_education_certifications_v1`;
  - sample questions are `type="button"`;
  - the "Show more" ARIA attributes, and the 900px media rule;
  - no `innerHTML` in the script, and the script reads `sources`, `answer_mode` and `latency_ms`;
  - the new colors' contrast;
  - no store wording.
- **Manual checks:** the model's answers and the rendered answer details, checked on the deployed instance (tasks group 7). Layout and focus, checked in a local browser without sending questions.

### 11. Build approach: Claude Code, no orchestrator, no model calls
- **What:** Claude Code implements the tasks directly. The agent orchestrator isn't run for this change.
- **No model calls during the build:**
  - tests use the fakes;
  - `verify_rag.py` and `test_setup.py` are edited but not run, because they call the real services;
  - local browser checks look at layout and focus without sending a question.
- **Why:** each orchestrator run and each question uses the owner's free Gemini quota. The owner wants that quota for testing the deployed change.
- **Model use after deploying:** one embedding request for the seed, and roughly eight chat and eight embedding requests for the manual question list.

## Risks / Trade-offs

- **[Risk] The model drifts from the rules**, for example by answering an off-topic question from general knowledge, or by using a pronoun. → The prompt states each rule plainly, and temperature is already 0.1. The manual question list catches regressions after deploys. Retrieval always supplies Kai context, which anchors answers.
- **[Risk] A fact is wrong or out of date.** → Every fact in the drafts below comes from the pasted profile. Facts that will age are anchored to dates.
- **[Risk] The profile panel and the documents drift apart.** Certifications and roles appear in both. → A page test checks that each certification on the page is named in `kai_education_certifications_v1`. When the profile changes, both files are edited together.
- **[Trade-off] Certificates have no verify links yet.** Until the owner supplies the URLs, the certificates are shown as text, which is weaker proof. → Each link is a one-line HTML edit, and no placeholder link ever ships.
- **[Trade-off] Seeding is not atomic.** For a moment between the upsert and the delete, a question can retrieve both old and new chunks. → This only happens during a seed the owner starts, and lasts about one request. A failed delete is reported as a 500, so the owner retries.
- **[Risk] Two seeds at once** can delete each other's chunks. → There is a single admin. The last seed to finish wins, and seeding again repairs it.
- **[Risk] Chunks added through the API outside the defaults are deleted** by the next default seed. → That's the intended rule, marked **BREAKING** in the proposal. Before the first seed, the owner lists the table's chunk IDs (see Migration Plan).
- **[Trade-off] The panel needs JavaScript on a phone.** Without JS, "Show more" can't open, and the skills and certifications stay hidden. → The chat needs JS anyway. On a desktop, everything shows without JS.
- **[Trade-off] The admin page still edits a copy of the code defaults.** → Existing behavior, out of scope. Permanent changes go in `default_documents.py`.

## Migration Plan

1. Merge `dark-theme-admin-sign-in-via-agents` first, then this change. CI must pass, and Render deploys from `main`.
2. Before seeding, run `select chunk_id from rag_chunks order by chunk_id;` in the Supabase SQL editor. Expect only the four policy chunks. If anything else is listed, decide whether to keep it before going on.
3. Seed once: sign in at `/admin` and save, or run the CLI `/seed` with `SEED_TOKEN` set. Expect `inserted: 10, removed: 4`.
4. Ask the manual questions in tasks.md on `/chat`.

**Rollback:**
1. Revert the merge commit. Render redeploys.
2. Because the reverted `/seed` only upserts, first delete the profile chunks: `delete from rag_chunks where chunk_id like 'kai\_%';`.
3. Reseed from `/admin` to restore the policy documents.

## Open Questions

- **Certificate verify URLs:** the Anthropic (Skilljar) and AWS (Credly) links are on the page. The Oracle link and the Microsoft transcript share link are still to come. Until then, those two are shown without a link (decision 6). Adding them changes no spec, design or task.
- **Pronouns:** the documents and prompt use the name "Kai" throughout and assume no pronouns. If Kai wants specific pronouns used, add one sentence to `kai_overview_v1` and one line to the prompt.
- **The other certifications and skills:** the paste shows only 4 of the 13 certifications and none of the 32 skills in full. More can be added later to `kai_education_certifications_v1`, `kai_expertise_v1` and the profile panel, together.

## Document drafts

The text to put in `DEFAULT_DOCUMENTS`. Every fact comes from the pasted profile. Every `source` is `https://www.linkedin.com/in/khavo2907/`.

**`kai_overview_v1`**: "Who Kai is"

> Who is Kai? Kha Vo, who goes by Kai, is a Team Lead and software engineer based in Ho Chi Minh City, Vietnam. Kai's LinkedIn headline is "Team Lead | Enterprise Software & AI Solutions | Forward Deployed Engineering | .NET & Azure". Kai has designed, developed and delivered enterprise software since 2014, more than 12 years as of 2026, combining hands-on engineering, technical leadership, system architecture, cloud engineering and production operations. Kai specializes in turning complex business requirements into scalable, reliable and maintainable software. At Orient Software Development Corp., Kai leads technical development for DEKRA's Global Vehicle Inspection Booking platform, working with international stakeholders and teams across multiple markets. Before that, Kai was a software engineer at DXC Technology Vietnam. Kai has worked in automotive inspection and booking, healthcare management, retail inventory, payment solutions, cloud computing and Microsoft 365 integrations, and is now expanding into generative AI and AI-powered enterprise applications. Kai's philosophy: understand the problem, engineer the solution, and own the outcome.

**`kai_current_role_v1`**: "Current role: DEKRA booking platform"

> Kai (Kha Vo) has worked full-time at Orient Software Development Corp. in Ho Chi Minh City since July 2016, in a hybrid setup. Kai is Team Lead for DEKRA's Global Vehicle Inspection Booking platform, a multi-tenant enterprise solution serving multiple international markets, and has worked onsite at DEKRA's headquarters in Germany. In technical leadership and delivery, Kai leads development activities with developers, product owners and international stakeholders, translates business requirements into technical designs and scalable solutions, and drives technical discussions, code reviews, problem-solving and continuous improvement. In enterprise software and architecture, Kai designs and develops backend services and REST APIs with C#, .NET, ASP.NET Core and SQL Server, and builds frontend applications with Angular and TypeScript. The work covers multi-tenant architecture, country-specific workflows, and third-party integrations including payment, SMS and CAPTCHA services.

**`kai_cloud_production_v1`**: "Azure and production work"

> On DEKRA's Global Vehicle Inspection Booking platform, Kai (Kha Vo) designs and maintains Microsoft Azure solutions using App Services, API Management, Azure Cache for Redis, Managed Identity and Private Endpoints. Kai improves scalability, performance, caching and distributed concurrency handling, and drives improvements in security, monitoring and cloud infrastructure. Kai troubleshoots complex production issues involving high traffic, duplicate bookings and system reliability, supports releases, production deployments and incident resolution, and works with infrastructure teams to keep the platform stable. In 2026 Kai was part of the team that got the platform running again over a weekend of unexpected production issues, working across three continents and time zones, and was thanked publicly by a DEKRA colleague. Kai's lesson from it: communication matters as much as technical skills, and sometimes the fastest path forward is picking up the phone and solving problems together.

**`kai_earlier_projects_v1`**: "Other enterprise projects"

> Besides the DEKRA platform, Kai (Kha Vo) has worked on other enterprise projects at Orient Software Development Corp.: CloudInc (cloud computing), ASPIT (healthcare management), TOG (retail inventory), ESPOS (payment solutions) and Rencore (Microsoft 365 and Azure). Across these projects Kai gained experience in healthcare, retail, payments, cloud computing and Microsoft 365 integrations, in addition to automotive inspection and booking.

**`kai_dxc_v1`**: "DXC Technology Vietnam (2014–2016)"

> From September 2014 to June 2016, Kai (Kha Vo) was a Software Engineer at DXC Technology Vietnam in Ho Chi Minh City. Kai was part of a 30-member development team on the Jurong Town Corporation (JTC) JIM project in Singapore, taking part in business requirement analysis and software development, implementing enterprise application features with the team, and contributing to problem-solving and project delivery. The role gave Kai experience in a large enterprise development team with structured software delivery processes.

**`kai_expertise_v1`**: "Core expertise"

> What can Kai do? Kha Vo (Kai) has core expertise in five areas. Enterprise software engineering: C#, .NET, ASP.NET Core, Angular, REST APIs, SQL Server and distributed applications. Cloud and distributed systems: Microsoft Azure, App Services, API Management, Azure Cache for Redis, cloud architecture, scalability and system reliability. Solution architecture: multi-tenant platforms, system integration, database design, distributed locking, caching strategies and performance optimization. Technical leadership: leading development activities, technical problem-solving, architecture discussions, mentoring, and collaboration with international stakeholders. Production engineering: troubleshooting complex production incidents and improving application performance, security, availability and operational reliability. Kai is also expanding into generative AI: large language models, retrieval-augmented generation (RAG), AI agents and AI-assisted software engineering.

**`kai_ai_focus_v1`**: "AI focus"

> Kai (Kha Vo) is actively expanding expertise in generative AI and AI-powered enterprise applications, with a focus on large language models (LLMs) and retrieval-augmented generation (RAG); AI agents and tool or function calling; AI-assisted software engineering and agentic development workflows; and applying AI to real-world enterprise business processes. Kai earned Anthropic's Claude Code in Action certification in March 2026, and lists GitHub Copilot and Replit Agent among the tools Kai uses. Kai follows the shift from the traditional software development lifecycle to an agentic one, in which AI agents write much of the code and people review and govern their work.

**`kai_education_certifications_v1`**: "Education and certifications"

> Kai (Kha Vo) holds an Engineer's Degree in Information Technology from Sai Gon University (2010 to 2014). Kai lists 13 licenses and certifications on LinkedIn, including Claude Code in Action from Anthropic (March 2026), AWS Educate Machine Learning Foundations from Amazon Web Services (July 2025), Oracle Cloud Infrastructure 2025 Certified AI Foundations Associate from Oracle (2025), and Microsoft Certified Professional with the Programming in C# exam. Kai also completed the code labs at Build with AI Ho Chi Minh City 2026 and received a certificate of completion.

**`kai_career_direction_v1`**: "Career direction"

> Kai (Kha Vo) is particularly interested in Forward Deployed Engineering opportunities at the intersection of AI, enterprise software and cloud engineering. Kai enjoys working closely with customers and business stakeholders to understand their challenges, design practical solutions, build working prototypes, and deliver technology that creates measurable business value. Kai's philosophy: understand the problem, engineer the solution, and own the outcome. For opportunities, or anything this profile doesn't cover, contact Kai on LinkedIn: https://www.linkedin.com/in/khavo2907/

**`kai_community_writing_v1`**: "Writing and community"

> Kai (Kha Vo) writes technical articles on Medium, including "Synchronous/Asynchronous programming … think more about the definition", which explores synchronous and asynchronous programming, threading and tasks, and "On the road to understand Microservices and demonstrate the concept with Clean Architecture", Kai's first article. Kai takes part in developer community events. In 2026 Kai joined Build with AI Ho Chi Minh City, organized by GDG Ho Chi Minh City with Google for Developers, with sessions on where Google AI is heading, vibe coding, deploying and observing AI agents on Google Cloud Run, and using the Gemini API to extract data from invoices and forms. Kai also joined DEV@Cafe – GitHub Copilot Dev Days 2026 at NashTech, including a multi-agent lab on AI agents collaborating on development tasks. Kai sees continuous learning as essential in tech.
