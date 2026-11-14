# Spec Delta

## Purpose

Makes the app a showcase for its owner, Kha Vo (known as Kai). It answers visitors' questions about Kai from documents written from Kai's public LinkedIn profile, and shows Kai's profile, skills and certifications. Covers what the default knowledge base holds and leaves out, how the assistant answers, and how the chat page and CLI present it.

## ADDED Requirements

### Requirement: The default knowledge base describes Kai
`/documents` SHALL return, and `/seed` without documents SHALL store, documents written from Kha Vo's public LinkedIn profile, one topic per document. Together they SHALL cover: who Kai is, the current role, the current role's cloud and production work, earlier projects, the earlier employer, core expertise, AI focus, education and certifications, career direction, and community activity and writing. No store policy document SHALL remain.

#### Scenario: Topics covered
- **WHEN** `/documents` is fetched
- **THEN** there is a separate document for each topic listed above, and every document ID is unique

#### Scenario: Store documents are gone
- **WHEN** `/documents` is fetched
- **THEN** no document has the ID `policy_returns_v1`, `policy_shipping_v1`, `sizing_guide_v1` or `support_contact_v1`, and no document text mentions a return policy, shipping, sizing or customer support

#### Scenario: Seeding the defaults
- **GIVEN** the knowledge base is empty
- **WHEN** `POST /seed` is sent without documents
- **THEN** every default document is stored as one or more chunks

### Requirement: Every default document has a title
Each default document SHALL have a short title that names its topic and differs from every other default document's title. The title is what visitors see when the document is listed as a source.

#### Scenario: Titles present
- **WHEN** `/documents` is fetched
- **THEN** every document has a non-empty `title`, and no two documents share one

### Requirement: Every default document names Kai
Each default document SHALL name "Kai" or "Kha Vo" in its text, so that a passage read on its own says whom it is about. The document about who Kai is SHALL state that Kha Vo goes by Kai.

#### Scenario: Nickname stated
- **WHEN** `/documents` is fetched
- **THEN** the document about who Kai is says that Kha Vo is known as Kai

#### Scenario: Passages shown without the model
- **GIVEN** the knowledge base holds the default documents and the chat model is unavailable
- **WHEN** a visitor asks "What does Kai do at DEKRA?"
- **THEN** each passage in the fallback answer names Kai or Kha Vo

### Requirement: The default knowledge base holds only public profile facts
The default documents SHALL state only facts shown on Kha Vo's public LinkedIn profile. They MUST NOT contain profile analytics or audience counts, other people's posts, the names of people other than Kha Vo, credential IDs, email addresses, phone numbers or street addresses.

#### Scenario: No analytics or audience counts
- **WHEN** `/documents` is fetched
- **THEN** no document mentions profile views, post impressions, search appearances, followers or connections

#### Scenario: No other people
- **WHEN** `/documents` is fetched
- **THEN** no document names a person other than Kha Vo; organizations and events, such as DEKRA, Orient Software and GDG Ho Chi Minh City, may be named

#### Scenario: No contact or credential details
- **WHEN** `/documents` is fetched
- **THEN** no document contains an email address, a phone number, a credential ID or the office's street address; the LinkedIn profile URL `https://www.linkedin.com/in/khavo2907/` may appear

### Requirement: The assistant talks about Kai in the third person
The assistant SHALL describe Kha Vo in the third person, by name, and SHALL treat "Kai" and "Kha Vo" as the same person. It MUST NOT write as if it were Kai, and MUST NOT accept offers, agree to meetings or state Kai's availability or rates on Kai's behalf.

#### Scenario: Who is Kai
- **GIVEN** the knowledge base holds the default documents
- **WHEN** a visitor asks "Who is Kai?"
- **THEN** the answer describes Kai in the third person as a Team Lead at Orient Software, and cites at least one document

#### Scenario: Full name
- **GIVEN** the knowledge base holds the default documents
- **WHEN** a visitor asks "Who is Kha Vo?"
- **THEN** the answer describes the same person as for "Who is Kai?"

#### Scenario: Asked to commit for Kai
- **WHEN** a visitor asks "Can Kai join a call with us next Tuesday?"
- **THEN** the answer says the assistant can't arrange that, suggests contacting Kai on LinkedIn, and doesn't agree to the call

### Requirement: Answers about Kai come only from the knowledge base
The assistant SHALL answer questions about Kai only from the retrieved documents, citing each document it uses. When they don't answer the question, it SHALL say that Kai's profile doesn't cover it and suggest contacting Kai on LinkedIn. It MUST NOT guess.

#### Scenario: What can Kai do
- **GIVEN** the knowledge base holds the default documents
- **WHEN** a visitor asks "What can Kai do?"
- **THEN** the answer summarizes Kai's expertise, such as .NET and Azure enterprise software, solution architecture, technical leadership, production engineering and AI applications, and cites the documents it uses

#### Scenario: Not in the profile
- **GIVEN** the knowledge base holds the default documents
- **WHEN** a visitor asks "What salary does Kai expect?"
- **THEN** the answer says Kai's profile doesn't cover it, suggests contacting Kai on LinkedIn, and states no figure

### Requirement: Questions that aren't about Kai are steered back
For a question that isn't about Kai, the assistant SHALL say briefly that it answers questions about Kai and suggest one. It MUST NOT answer from general knowledge. It SHALL answer greetings briefly and offer help.

#### Scenario: Old store question
- **WHEN** a visitor asks "What is your return policy?"
- **THEN** the answer says the assistant answers questions about Kai, gives no return-policy information and no support contact details

#### Scenario: Greeting
- **WHEN** a visitor says "Hi"
- **THEN** the answer is a short greeting that offers to answer questions about Kai

### Requirement: The chat page presents the profile assistant
`/chat` SHALL have the title and heading "Meet Kai", a subtitle saying it answers questions about Kha Vo's experience and skills, a welcome message with sample questions including "Who is Kai?" and "What can Kai do?", and an input placeholder inviting questions about Kai. It MUST NOT mention returns, shipping, sizing, policies or customer support.

#### Scenario: Page content
- **WHEN** `/chat` is fetched
- **THEN** its `<title>` and `<h1>` are "Meet Kai", and its welcome message contains the sample questions "Who is Kai?" and "What can Kai do?"

#### Scenario: No store wording
- **WHEN** `/chat` is fetched
- **THEN** no text shown on the page contains "Customer Support", "returns", "shipping", "sizing" or "policies"

#### Scenario: Link back from the sign-in page
- **WHEN** `/admin/login` is fetched
- **THEN** its link back to `/chat` doesn't say "Customer Support"

### Requirement: Sample questions are asked with one click
Each sample question SHALL be a button. Activating it with a click, Enter or Space SHALL send that question exactly as if the visitor had typed it and pressed Send. While a question is waiting for its answer, the sample questions and Send SHALL be disabled, and pressing Enter in the input SHALL NOT send another question.

#### Scenario: Clicking a sample question
- **WHEN** a visitor clicks "What can Kai do?"
- **THEN** "What can Kai do?" appears as the visitor's message and is sent to `/answer`

#### Scenario: Waiting for an answer
- **WHEN** a question has been sent and its answer hasn't arrived
- **THEN** the sample questions and Send can't be activated, and pressing Enter in the input sends nothing

### Requirement: The chat page shows Kai's profile, skills and certifications
`/chat` SHALL show a profile panel with:
- the name Kha Vo and the nickname Kai;
- the LinkedIn headline;
- Ho Chi Minh City, Vietnam, and 12+ years of experience;
- the current role;
- a link to `https://www.linkedin.com/in/khavo2907/`;
- skills as tags in two groups, "Enterprise & cloud" and "AI";
- the four certifications, each with its issuer.

#### Scenario: Profile panel content
- **WHEN** `/chat` is fetched
- **THEN** the profile panel contains "Kha Vo", "Kai", the LinkedIn link, the "Enterprise & cloud" and "AI" skill groups, and the certifications Claude Code in Action, AWS Educate Machine Learning Foundations, Oracle Cloud Infrastructure 2025 Certified AI Foundations Associate and Microsoft Certified Professional, with "Programming in C#" shown as its detail

#### Scenario: Same facts as the knowledge base
- **WHEN** `/chat` and `/documents` are fetched
- **THEN** every certification named on the page is also named in the education and certifications document

### Requirement: Links on the chat page go only where intended
A certification with a configured verification URL SHALL link to it, and one without SHALL be shown as plain text, never as an empty or placeholder link. Every link to another site SHALL open in a new tab without giving that page access to the chat page. The chat page SHALL NOT link to GitHub.

#### Scenario: Certification without a URL
- **GIVEN** no verification URL is configured for a certification
- **WHEN** `/chat` is fetched
- **THEN** that certification is shown as text, and no link on the page has an empty href or `#`

#### Scenario: Links to other sites
- **WHEN** `/chat` is fetched
- **THEN** every link to another site has `target="_blank"` and a `rel` containing `noopener` and `noreferrer`

#### Scenario: No GitHub link
- **WHEN** `/chat` is fetched
- **THEN** no link points to `github.com`

### Requirement: The profile panel fits the screen
At 900 pixels wide and wider, the profile panel SHALL sit beside the chat, fully shown. Narrower, a short card with the name, headline and LinkedIn link SHALL sit above the chat, with the skills and certifications behind a "Show more" button that reports whether it is expanded.

#### Scenario: Desktop
- **WHEN** `/chat` is shown 1280 pixels wide
- **THEN** the profile panel and the chat are side by side, and the skills and certifications are visible without pressing anything

#### Scenario: Phone
- **WHEN** `/chat` is shown 375 pixels wide
- **THEN** the short card is above the chat, the skills and certifications are hidden, "Show more" has `aria-expanded="false"`, and the page doesn't scroll sideways

#### Scenario: Show more
- **GIVEN** `/chat` is shown 375 pixels wide
- **WHEN** the visitor activates "Show more"
- **THEN** the skills and certifications appear, the button reads "Show less", and it has `aria-expanded="true"`

### Requirement: Each answer shows its sources and how it was made
Under each answer with sources, the chat page SHALL list them numbered and by title, and SHALL show each citation marker in the answer as the matching number, such as [1]. Activating a title SHALL show that passage's text. The page SHALL show "AI answer" for a generated answer and "Passages only (AI unavailable)" for an extractive one, with the response time in seconds.

#### Scenario: Generated answer
- **GIVEN** `/answer` responds with `answer_mode` `generated`, `latency_ms` 1234, and two sources titled "Who Kai is" and "Core expertise"
- **WHEN** the answer is shown
- **THEN** the sources are listed as "[1] Who Kai is" and "[2] Core expertise", collapsed, the answer's citation markers read [1] and [2], and the line under the answer reads "AI answer · 1.2 s"

#### Scenario: Reading a source
- **WHEN** the visitor activates the source "Core expertise", by click or by keyboard
- **THEN** that source's passage text is shown below its title

#### Scenario: Fallback answer
- **GIVEN** `/answer` responds with `answer_mode` `extractive`
- **WHEN** the answer is shown
- **THEN** its sources are listed, and the line under it reads "Passages only (AI unavailable)" with the response time

#### Scenario: No sources
- **GIVEN** `/answer` responds with `answer_mode` `no_results` or `error`
- **WHEN** the answer is shown
- **THEN** no sources list and no mode line are shown

### Requirement: Questions and answers are shown as plain text
The chat page SHALL show the visitor's question, the answer, source titles and passages as plain text, keeping line breaks. Markup in them MUST NOT be interpreted as HTML.

#### Scenario: Markup in an answer
- **GIVEN** `/answer` responds with text containing `<img src=x onerror=alert(1)>`
- **WHEN** the answer is shown
- **THEN** the characters `<img src=x onerror=alert(1)>` are shown as written, no image element is created, and no script runs

### Requirement: The CLI chatbot presents the profile assistant
The CLI chatbot's welcome text and help examples SHALL invite questions about Kai, and SHALL include "Who is Kai?" and "What can Kai do?" as examples. They MUST NOT mention returns, shipping, sizing or policies.

#### Scenario: Help examples
- **WHEN** the user runs the chatbot's `/help` command
- **THEN** the examples include "Who is Kai?" and "What can Kai do?", and none is about returns, shipping, sizing or policies
