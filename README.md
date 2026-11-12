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
To edit and seed documents in the browser, open the admin page at [http://localhost:8000/admin](http://localhost:8000/admin). When `SEED_TOKEN` is set, it asks for that token first. Or use the API:

```bash
# Seed with default documents
curl -X POST http://localhost:8000/seed

# Or seed with custom documents
curl -X POST http://localhost:8000/seed \
  -H "Content-Type: application/json" \
  -d '{
    "docs": [
      {
        "chunk_id": "policy_returns_v1#window",
        "source": "https://help.example.com/returns",
        "text": "You can return unworn items within 30 days of purchase..."
      }
    ]
  }'
```

### Ask Questions (RAG)
```bash
curl -X POST http://localhost:8000/answer \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Can I return shoes after 30 days?",
    "top_k": 6
  }'
```

**Example Response:**
```json
{
  "text": "Based on our return policy, you can return unworn shoes within 30 days of purchase [policy_returns_v1#window]. Items must be in original condition...",
  "citations": ["policy_returns_v1#window", "policy_returns_v1#conditions"],
  "debug": {
    "top_doc_ids": ["policy_returns_v1#window", "policy_returns_v1#conditions"],
    "latency_ms": 1250
  }
}
```

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
├── sql/
│   └── init_supabase.sql # Database setup script
├── .env.example          # Environment template
├── requirements.txt      # Python dependencies
├── Dockerfile           # Container configuration
└── README.md           # This file
```

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
