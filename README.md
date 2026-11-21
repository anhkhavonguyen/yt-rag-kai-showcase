# RAG AI Agent Backend

[![CI](https://github.com/anhkhavonguyen/yt-rag-kai-showcase/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/anhkhavonguyen/yt-rag-kai-showcase/actions/workflows/ci.yml)
[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/anhkhavonguyen/yt-rag-kai-showcase)

Run it for free: Render + Google Gemini + Supabase, no payment method needed. See the [free deployment guide](DEPLOYMENT.md).

A minimal, production-ready FastAPI backend demonstrating **Retrieval-Augmented Generation (RAG)** with vector similarity search. Built for educational purposes and easy frontend integration.


## 🎯 Features

- **FastAPI** backend with automatic API documentation
- **Supabase** integration with pgvector for vector similarity search
- **Multi-AI Provider** support (OpenAI & Anthropic)
- **Vector embeddings** with semantic search
- **Citation-based answers** with source tracking
- **Frontend-ready** architecture for NextJS integration
- **Docker** containerization for easy deployment

## 🏗️ Architecture

```
yt-rag/
├── app/
│   ├── core/           # Infrastructure (config, database)
│   ├── models/         # Pydantic data models
│   ├── services/       # Business logic (RAG, embeddings)
│   └── main.py         # FastAPI application
├── sql/
│   └── init_supabase.sql  # Database initialization script
└── requirements.txt
```

## 🚀 Quick Start Guide

**Complete setup from clone to asking questions in ~10 minutes**

### Prerequisites

- Python 3.11+
- Supabase account
- OpenAI API key
- Anthropic API key (optional, for Claude)

### Step 1: Clone and Install Dependencies

```bash
# Clone the repository
git clone https://github.com/ShenSeanChen/yt-rag.git
cd yt-rag

# Create virtual environment
python3.11 -m venv venv_yt_rag
source venv_yt_rag/bin/activate  # On Windows: venv_yt_rag\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Step 2: Get API Keys (5 minutes)

**Supabase Setup:**
1. Go to [supabase.com](https://supabase.com) and create a new project
2. Wait for project to be ready (~2 minutes)
3. Go to **Settings** → **API** and copy:
   - **Project URL** (e.g., `https://abc123.supabase.co`)
   - **Anon public key** (starts with `eyJ...`)
   - **Service role secret key** (starts with `eyJ...`)

**OpenAI Setup:**
1. Go to [platform.openai.com](https://platform.openai.com)
2. Create account/sign in → **API Keys** → Create new key
3. Copy the key (starts with `sk-...`)

If you meet issues accessing overseas services due to the lack of a Visa or Mastercard, please check out [the alternative version](https://github.com/ZhaoYi-10-13/Gary-Agent-RAG) of this repository. That version uses Chinese APIs to ensure the project runs smoothly (Supabase is still required, but the free tier fully covers this project).

### Step 3: Configure Environment

```bash
# Copy environment template
cp .env.example .env

# Edit with your real API keys
nano .env  # or use your preferred editor
```

**Update `.env` with your values:**
```env
# Supabase Configuration
SUPABASE_URL=https://your-project-ref.supabase.co
SUPABASE_ANON_KEY=your_anon_key_here
SUPABASE_SERVICE_ROLE_KEY=your_service_role_key_here

# OpenAI Configuration (using latest models)
OPENAI_API_KEY=sk-your_openai_key_here
OPENAI_EMBED_MODEL=text-embedding-3-large
OPENAI_CHAT_MODEL=gpt-4o

# AI Provider
AI_PROVIDER=openai

# Optional: Anthropic
ANTHROPIC_API_KEY=your_anthropic_key_here
ANTHROPIC_CHAT_MODEL=claude-3-5-sonnet-20241022
```

### Step 4: Initialize Database (2 minutes)

1. **Open Supabase Dashboard** → **SQL Editor**
2. **Click "New query"**
3. **Copy entire contents** of `sql/init_supabase.sql`
4. **Paste and click "Run"**

✅ This creates everything needed:
- pgvector extension
- `rag_chunks` table with VECTOR(3072) for latest embeddings
- Performance indexes
- Vector search functions
- RLS policies for future auth

### Step 5: Test Setup (Optional)

```bash
# Test your complete setup
python test_setup.py
```

This verifies:
- ✅ Dependencies installed
- ✅ API keys configured
- ✅ Database connected
- ✅ Schema initialized
- ✅ RAG pipeline working

### Step 6: Start the Server

```bash
uvicorn main:app --reload --port 8000
```

The API will be available at:
- **API**: http://localhost:8000
- **Interactive Docs**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

## 📚 API Usage

### Health Check
```bash
curl http://localhost:8000/healthz
```

### Seed Knowledge Base
To edit and seed documents in the browser, open the admin page at [http://localhost:8000/admin](http://localhost:8000/admin). When `SEED_TOKEN` is set, it first sends you to the sign-in page at `/admin/login`, where you sign in with that token. The session lasts 8 hours or until you sign out. Or use the API:

```bash
# Seed with the default documents (Kha Vo's profile, from app/data/default_documents.py)
curl -X POST http://localhost:8000/seed

# Or seed with custom documents
curl -X POST http://localhost:8000/seed \
  -H "Content-Type: application/json" \
  -d '{
    "docs": [
      {
        "chunk_id": "kai_overview_v1",
        "source": "https://www.linkedin.com/in/khavo2907/",
        "text": "Who is Kai? Kha Vo, who goes by Kai, is a Team Lead..."
      }
    ]
  }'
```

**A seed replaces the whole knowledge base.** The new chunks are embedded and saved first, and then every chunk that wasn't in this seed is deleted. If embedding or saving fails, nothing is deleted. The response says how many chunks were saved and how many old ones were removed:

```json
{"inserted": 10, "removed": 4}
```

### Ask Questions (RAG)
```bash
curl -X POST http://localhost:8000/answer \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What can Kai do?",
    "top_k": 6
  }'
```

**Example Response:**
```json
{
  "text": "Kai has core expertise in enterprise software with C#, .NET and Azure, solution architecture, technical leadership and production engineering [kai_expertise_v1#1], and is expanding into generative AI such as RAG and AI agents [kai_ai_focus_v1#1].",
  "citations": ["kai_expertise_v1#1", "kai_ai_focus_v1#1"],
  "sources": [
    {"chunk_id": "kai_expertise_v1#1", "title": "Core expertise", "text": "What can Kai do? Kha Vo (Kai) has core expertise in five areas..."},
    {"chunk_id": "kai_ai_focus_v1#1", "title": "AI focus", "text": "Kai (Kha Vo) is actively expanding expertise in generative AI..."}
  ],
  "debug": {
    "top_doc_ids": ["kai_expertise_v1#1", "kai_ai_focus_v1#1", "kai_overview_v1#1", "kai_current_role_v1#1"],
    "latency_ms": 1250,
    "answer_mode": "generated"
  }
}
```

`sources` holds one entry per citation, in the same order: the cited passage and the title of its document. The chat page lists them under each answer.

## 🔧 Configuration Options

### AI Providers

Chat and embeddings go through an OpenAI-compatible API. `OPENAI_BASE_URL` points it at any compatible provider (unset means api.openai.com), and `OPENAI_API_KEY` holds that provider's key.

**Google Gemini (free tier, no billing)**
```env
AI_PROVIDER=openai
OPENAI_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
OPENAI_API_KEY=your_gemini_api_key        # from Google AI Studio
OPENAI_CHAT_MODEL=gemini-3.5-flash
OPENAI_EMBED_MODEL=gemini-embedding-2
EMBEDDING_DIMENSIONS=1536                 # vectors are shortened to match VECTOR(1536)
```

**OpenAI**
```env
AI_PROVIDER=openai
OPENAI_API_KEY=your_key
OPENAI_EMBED_MODEL=text-embedding-3-small  # 1536 dimensions
OPENAI_CHAT_MODEL=gpt-4o-mini
```

**Anthropic Claude**
```env
AI_PROVIDER=anthropic
ANTHROPIC_API_KEY=your_key
ANTHROPIC_CHAT_MODEL=claude-3-haiku-20240307

# Note: Still need OpenAI key for embeddings
OPENAI_API_KEY=your_openai_key
```

### RAG Parameters

Adjust in `app/core/config.py`:
- `chunk_size`: Token limit per chunk (default: 400)
- `chunk_overlap`: Overlap between chunks (default: 60 tokens)
- `default_top_k`: Number of chunks to retrieve (default: 6)
- `temperature`: LLM creativity (default: 0.1)

### Observability (optional)

Each `/answer` and `/seed` can be traced in [Datadog Agent Observability](https://www.datadoghq.com/product/llm-observability/) on its free plan. One trace shows embedding, the passages found and their scores, the Gemini prompt and answer, token counts and the outcome. Tracing is off until `DD_API_KEY` is set.

```env
DD_API_KEY=your_datadog_api_key       # empty = tracing off
DD_SITE=ap1.datadoghq.com             # your Datadog account's site (default datadoghq.com)
DD_LLMOBS_ML_APP=yt-rag               # application name in Datadog (default yt-rag)
OBSERVABILITY_ENABLED=true            # false = off even with a key
OBSERVABILITY_CAPTURE_TEXT=true       # false = metadata only, no question/passage/answer text
```

Free sign-up, finding traces and what is sent: [DEPLOYMENT.md → Datadog Agent Observability](DEPLOYMENT.md#6-optional-datadog-agent-observability-free). Each traced answer also carries rule-based checks, such as whether its citations are valid. They make no extra model calls; see [DEPLOYMENT.md → Answer checks](DEPLOYMENT.md#answer-checks).

## 🐳 Docker Deployment

```bash
# Build image
docker build -t yt-rag .

# Run container
docker run -p 8080:8080 --env-file .env yt-rag
```

To host this image for free, see the [free deployment guide](DEPLOYMENT.md) (Render web service defined in [`render.yaml`](render.yaml)).

## 🔮 NextJS Frontend Integration

This backend is designed for seamless frontend integration:

**Frontend Setup (NextJS)**
```javascript
// lib/supabase.js
import { createClient } from '@supabase/supabase-js'

const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL,
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY
)

// API calls to your backend
const response = await fetch('http://localhost:8000/answer', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ query: 'user question' })
})
```

**Future Auth Integration**
When adding Google authentication:
1. Enable Google Auth in Supabase
2. The RLS policies are already configured
3. Frontend and backend will share the same Supabase client
4. No backend changes needed!

## 📁 Project Structure

```
yt-rag/
├── app/
│   ├── core/
│   │   ├── config.py      # Environment & settings
│   │   └── database.py    # Supabase client & operations
│   ├── models/
│   │   ├── requests.py    # API request schemas
│   │   ├── responses.py   # API response schemas
│   │   └── entities.py    # Database entities
│   ├── services/
│   │   ├── embedding.py   # AI provider abstraction
│   │   ├── rag.py        # RAG pipeline logic
│   │   └── chunker.py    # Text processing utilities
│   └── main.py           # FastAPI app & routes
├── evals/                # Offline answer evaluation (python -m evals)
│   └── questions/        # The answers and guardrails question sets
├── sql/
│   └── init_supabase.sql # Database setup script
├── .env.example          # Environment template
├── requirements.txt      # Python dependencies
├── Dockerfile           # Container configuration
└── README.md           # This file
```

## 🧪 Evaluating answers

`python -m evals` asks a fixed set of questions about Kai through your local copy of the RAG pipeline and checks each answer with fixed rules. No model grades the answers. Run it before and after changing the prompt, the model, the documents or retrieval, to see whether answers got better or worse.

The questions live in [`evals/questions/`](evals/questions/), in two sets:

- **answers** (8 questions): questions Kai's profile covers, such as "Who is Kai?" and "Which Azure services has Kai worked with?". Each lists the documents that should be found and cited, and phrases the answer must contain.
- **guardrails** (5 questions): questions the assistant must deflect: a salary question, an off-topic question, a request to book a call, a greeting, and a general-knowledge question. Each lists phrases the answer must contain, such as "LinkedIn", and phrases it must not contain, such as a salary figure.

### Before you run it

- A `.env` with the Gemini and Supabase settings, as in [Running locally with Gemini](DEPLOYMENT.md#running-locally-with-gemini).
- A knowledge base seeded with the default documents (`POST /seed`). The run only reads the knowledge base; it never changes it.

### Run it

```bash
python -m evals                                  # both sets: 13 questions
python -m evals --set guardrails                 # one set
python -m evals --only who-is-kai salary         # chosen questions, from either set
python -m evals --local                          # never send results to Datadog
python -m evals --delay 10                       # seconds between questions (default 5)
```

**Cost:** each question makes about 2 Gemini requests, one embedding and one chat. A full run is about 26 requests, and `--set guardrails` about 10. Questions are asked one at a time, 5 seconds apart by default, to stay within the free tier's per-minute limits. If Gemini still rate-limits a question, its answer falls back to `extractive` and the report says **model unavailable**. Raise `--delay` and rerun that question with `--only`.

### Read the report

```text
answers
  PASS  who-is-kai
  FAIL  azure-work         cites_expected_source, mentions_required=0.50
  FAIL  ai-focus           model unavailable (extractive)
guardrails
  PASS  salary
answers 6/8 · guardrails 5/5 · total 11/13
```

A question passes only when the model answered (`answer_mode` `generated`) and every check passed:

| Check | Set | Passes when |
|---|---|---|
| `retrieval_hit` | answers | An expected document is among the passages given to the model |
| `cites_expected_source` | answers | The answer cites an expected document |
| `mentions_required` | both | The answer contains every required phrase (shown as a fraction when it doesn't) |
| `avoids_forbidden` | guardrails | The answer contains no forbidden phrase |
| `citations_valid` | both | Every `[chunk_id]` in the answer names a passage the model was given |
| `plain_text` | both | The answer has no Markdown (`**`, backticks, `#` headings) |

Phrases match without regard to case. Exit status: `0` every question passed, `2` any question failed, `1` the run couldn't start, for example because of missing settings, an unknown question ID or a Datadog key that was rejected.

### Record runs in Datadog (optional, free)

With Datadog keys in your local `.env`, each set run is also recorded as a Datadog **experiment** in the project `yt-rag`. Each question's record shows the answer, the checks, and its embedding, retrieval and chat steps. Each run also records its settings (chat model, embedding model, `top_k`, temperature and commit), so you can compare runs in Datadog's experiment view. The report ends with a link to each experiment.

1. Set up Datadog and `DD_API_KEY` / `DD_SITE` as in [DEPLOYMENT.md → Datadog](DEPLOYMENT.md#6-optional-datadog-agent-observability-free).
2. Create an **application key**: **Organization Settings → Application Keys → New Key**. Experiments need it in addition to the API key.
3. Add it to your **local** `.env` only:

   ```env
   DD_APP_KEY=your_datadog_application_key
   ```

   An application key acts with your Datadog user's permissions. **Never** add it to Render or `render.yaml`: the web app doesn't use it. Revoke it in Datadog when you no longer run evaluations.

Without both keys, or with `--local`, the run says `Datadog: results stay local (…)` and sends nothing.

What to expect in Datadog:

- **Datasets.** Each set's questions are uploaded once as a dataset named `yt-rag-<set>-<hash>`. Runs with unchanged questions reuse it, so their experiments line up. Editing a question creates a new dataset.
- **Content.** Experiment records hold the test questions and the model's answers. These are your own test questions, not visitor data. `OBSERVABILITY_CAPTURE_TEXT` still applies to the pipeline steps inside them.
- **Traces from runs.** A run also creates traces tagged with your local `ENVIRONMENT`, usually `development`. Filter by `env:production` to see only visitor traffic.
- **Cost and retention.** A full run adds about 13 LLM spans, far below the Free plan's 40K a month. Experiments are kept at least 15 days on the Free plan.

### Add a question

1. Add an entry to `evals/questions/answers.json` or `guardrails.json`, with a unique `id` (lowercase letters, digits and hyphens).
   - An **answers** question needs `expected_documents` (IDs from [`app/data/default_documents.py`](app/data/default_documents.py)) and `required` phrases.
   - A **guardrails** question needs `required` and `forbidden` phrases.
   - A `required` entry can be a list of alternatives, any one of which counts: `["RAG", "retrieval-augmented"]`.
2. Run `pytest tests/test_eval_sets.py`. It validates the files without calling any service.
3. Run the new question with `python -m evals --only <id>`. Keep phrases short and distinctive, so harmless rewording doesn't fail them.

### How it's built

Answer quality is measured in two places. Both use the same rules, from [`app/services/answer_checks.py`](app/services/answer_checks.py), so an answer is judged the same way in an evaluation run and in production. No model grades answers anywhere; every check is a fixed rule.

| Part | When it runs | What it does | Gemini cost |
|---|---|---|---|
| **Offline evaluation** (`python -m evals`) | On demand, on your machine | Asks the 13 questions through your local pipeline, checks each answer, prints a report, and can record Datadog experiments | About 2 requests per question |
| **Live answer checks** | On every `/answer`, when [Datadog tracing](DEPLOYMENT.md#answer-checks) is on | Adds `retrieval_top_score`, `cites_sources`, `citations_valid` and `plain_text` to the answer's trace | None |

| Path | Purpose |
|---|---|
| `evals/questions/answers.json`, `evals/questions/guardrails.json` | The two question sets |
| `evals/sets.py` | Loads and validates the sets, and names each Datadog dataset by a hash of its questions |
| `evals/checks.py` | The checks and the pass rule |
| `evals/runner.py` | Asks the questions one at a time, locally or as Datadog experiments |
| `evals/report.py` | The printed report |
| `evals/__main__.py`, `evals/config.py` | The command line, and reading `DD_APP_KEY` |
| `app/services/answer_checks.py` | Citation and Markdown rules, shared with the live checks |
| `app/services/rag.py`, `app/core/observability.py` | Attach the live checks to each `/answer` trace |
| `tests/test_eval_*.py`, `tests/test_answer_checks.py`, `tests/test_live_evaluations.py` | Tests. They use fakes and never call Gemini, Supabase or Datadog |

Decisions worth remembering:

- **Two question sets, not one.** Every check applies to every question in its set. Datadog would otherwise record "not applicable" answers as a different kind of value under the same label.
- **The run is scored the same way with or without Datadog.** A recorded run scores each answer locally too, so its report matches a `--local` run exactly.
- **A Datadog problem is caught before any question is asked.** The run prepares the datasets first, so a rejected key costs no Gemini quota.
- **`.env` can hold keys the app doesn't use**, such as `DD_APP_KEY`. The app's settings ignore unknown lines, so a misspelled setting name in `.env` is ignored too rather than stopping startup. A missing required setting still stops it.
- **`evals/` isn't in the Docker image** (`.dockerignore`). The deployed service doesn't need it or `DD_APP_KEY`.

The proposal, spec, design and task list are in [`openspec/changes/datadog-rag-evaluation/`](openspec/changes/datadog-rag-evaluation/).

**Status (November 2026):** built, and tested with fakes. Four checks are still to do, tracked in group 7 of that change's `tasks.md`:
- a Docker build;
- a first guardrails run;
- a full run recorded in Datadog;
- checking the live checks on a deployed trace.

## 🤖 Agent Orchestrator

A separate learning example in [`orchestrator/`](orchestrator/README.md). A back-end agent writes a small FastAPI app, a front-end agent writes the page that calls it, and a reviewer agent checks both. An orchestrator routes each review issue to the agent that owns it until the reviewer approves. It uses the same `OPENAI_*` settings as the app, so it runs on Gemini's free tier, and it needs no Supabase settings.

```bash
python -m orchestrator "a to-do list app"
```

See [orchestrator/README.md](orchestrator/README.md) for the flow, the options, what each run saves and how to run the generated app.

## 🛠️ Development

### Running checks locally

CI (GitHub Actions, [.github/workflows/ci.yml](.github/workflows/ci.yml)) runs these same checks on every push and pull request to `main`. You don't need API keys to run them. The tests use placeholder settings and replace OpenAI, Anthropic and Supabase with test doubles, even if your machine has a real `.env`.

```bash
# Install runtime + development dependencies (pytest, ruff)
pip install -r requirements-dev.txt

# Lint (same pinned ruff version and rule set as CI)
ruff check .

# Tests (offline, no credentials needed)
pytest

# Optional: check that the Docker image still builds
docker build -t yt-rag:ci .
```

`test_setup.py`, `verify_rag.py` and `check_dimensions.py` are manual scripts that talk to real services. `pytest` does not run them.

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙋‍♂️ Support
---

**Built with ❤️ for the developer community**

*This project demonstrates modern RAG architecture patterns and is perfect for learning, prototyping, or building production applications.*

<!-- sponsors --><!-- sponsors -->
