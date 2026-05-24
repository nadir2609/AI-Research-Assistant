# 🔬 AI Research Assistant

> **Advanced Async Research Question Answering System**
> Fetches Wikipedia, arXiv, and web search results **in parallel**, synthesizes answers with LLM-powered citations, and caches results intelligently.

---

## 📋 Table of Contents

- [Quick Start](#quick-start)
- [Features](#features)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
  - [CLI](#cli)
  - [HTTP API](#http-api)
  - [Docker](#docker)
- [Architecture](#architecture)
- [Database](#database)
- [Performance](#performance)
- [Testing](#testing)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)

---

## 🚀 Quick Start

### Option A — Local Python

```bash
python -m venv .venv

# macOS / Linux
source .venv/bin/activate

# Windows PowerShell
.\.venv\Scripts\Activate.ps1

pip install -r requirements-runtime.txt

pip install -r requirements-test.txt  # optional for tests

cp .env.example .env
# edit .env with keys if needed

# CLI
python -m researcher ask "What is photosynthesis and what are its main stages?"

# UI app
uvicorn ui_app:ui_app --reload
```

### Option B — Run with Docker

```powershell
docker compose up --build
```

Optional helpers:

```powershell
# detached mode
docker compose up --build -d

# stop stack
docker compose down
```

---

## ✨ Features

- Parallel source fetch (Wikipedia, arXiv, web) with per-source timeouts
- Shared httpx AsyncClient for connection reuse
- Two-tier cache: filesystem JSON + PostgreSQL
- Retries with exponential backoff, jitter, and rate-limit handling
- Token-bucket rate limiting per provider
- Input validation and output sanitization
- CLI and FastAPI HTTP API
- Docker Compose stack with health checks
- Offline tests using mocked HTTP/DB

---

## 📦 Installation

Prerequisites: Python 3.12+, Docker (optional), optional PostgreSQL for persistence.

Clone:

```bash
git clone https://github.com/nadir2609/AI-Research-Assistant.git
cd AI-Research-Assistant
```

Follow Quick Start (Docker or Local Python) above.

---

## ⚙️ Configuration

Copy the template and set provider keys and tuning variables:

```bash
cp .env.example .env
# or for Docker
cp .env.docker.example .env
```

Important env vars (examples):

- `LLM_PROVIDER`: anthropic | openai | gemini
- `LLM_MODEL`: provider-specific model
- `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `GOOGLE_API_KEY`
- `WEB_SEARCH_PROVIDER`: tavily | serper | duckduckgo
- `TAVILY_API_KEY` / `SERPER_API_KEY` (when required)
- `DATABASE_URL`: postgresql://user:password@host:port/db
- `CACHE_DIR`: ./.cache
- `CACHE_TTL_SECONDS`: 86400
- `PER_SOURCE_TIMEOUT_SECONDS`: 10
- `MAX_SOURCES_PER_QUERY`: 3
- `EXTERNAL_MAX_RETRIES`: 3
- `LOG_LEVEL`: INFO

See `.env.example` and `src/config.py` for the full list and defaults.

---

## 📖 Usage

### CLI

Basic:

```bash
python -m researcher ask "What is photosynthesis and what are its main stages?"
```

Select sources:

```bash
python -m researcher ask "What is photosynthesis and what are its main stages?"
```

Bypass cache:

```bash
python -m researcher ask "What is photosynthesis and what are its main stages?" --no-cache
```

Output includes synthesized answer, numbered citations, and per-source fetch summary.

### HTTP API

Run server (dev):

```bash
#ui
uvicorn ui_app:ui_app --reload
# only api
uvicorn src.api:app --reload 
```

Health:

```bash
curl http://127.0.0.1:8000/health
# {"status":"ok"}
```

Ask (example):

```bash
curl -s -X POST http://127.0.0.1:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question":"What is photosynthesis and what are its main stages?","sources":["wiki","arxiv"],"no_cache":false}'
```

Response contains question, answer, citations, degraded flag, and fetch_results metadata.

### Docker

Start stack:

```bash
docker compose up --build
```

Run offline demo profile (no keys):

```bash
docker compose --profile demo run --rm demo
```

Run CLI inside container:

```bash
docker compose run --rm app python -m researcher ask "What is photosynthesis and what are its main stages?"
```

---

## 🏗 Architecture (high level)

- Entry: CLI (`researcher`) or FastAPI (`src/api.py`)
- Validation and sanitization (`src/validation.py`)
- ResearchService coordinates cache, orchestrator, and synthesis (`src/services/research_service.py`)
- ResearchOrchestrator runs parallel fetches (`src/concurrency/orchestrator.py`)
- ExternalCallPolicy provides retries, rate limits, and concurrency guards (`src/services/external_policy.py`)
- Storage: filesystem cache + PostgreSQL repository (`src/storage/`)
- AI module (`ai/`) provides `fetch_wikipedia`, `fetch_arxiv`, `fetch_web`, and `synthesize` (do not modify)

Refer to `SOFTWARE_PROJECT.tex` for diagrams and rationale used in the course report.

---

## 🗄 Database

Docker Compose creates and initializes Postgres with `docker/postgres/01-init.sql`.

Tables of interest:

- `research_cache(source_type, query_text, content JSONB, created_at)`
- `research_history(id, question, answer JSONB, sources JSONB, created_at)`

Use `DATABASE_URL` to point to a PostgreSQL instance when you want persistent cache & history.

---

## 📊 Performance

- Parallel fetching reduces wall-clock to ~max(source latencies) + synthesis time (not sum).
- Caching reduces repeat query latency dramatically.
- Rate limits (token bucket) protect providers and avoid 429s.

---

## 🧪 Testing

Run all tests:

```bash
pytest -v
pytest --cov=src --cov-report=term-missing
```

The tests are offline and mock external HTTP and DB, including the mandatory smoke test `tests/test_ai_smoke.py`.

---

## 🔧 Troubleshooting

- If API won't start due to missing keys, set `REQUIRE_PROVIDER_KEYS=false` in `.env` (only for local/demo use).
- If Postgres port 5432 is in use, stop local Postgres or change ports in `docker-compose.yml`.
- If container shows stale code, rebuild with `docker compose build --no-cache`.

For detailed debugging set `LOG_LEVEL=DEBUG` in `.env`.

---

## 🤝 Contributing

Please open issues or PRs. Do not modify files under `ai/` (course contract). Follow project style, include tests for new features.

---

**Last updated:** May 24, 2026
