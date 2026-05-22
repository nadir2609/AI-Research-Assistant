# Async Research Assistant (Topic 4)

**AI Academy — Software Engineering Final Project · Spring 2026**

Answers research questions by fetching **Wikipedia**, **arXiv**, and **web search** in parallel, then synthesizing a cited summary with an LLM. The course provides the `ai/` package; this repo is the **software-engineering layer**: configuration, caching, concurrency, retries, validation, logging, CLI, HTTP API, PostgreSQL, tests, and Docker.

| | |
|---|---|
| **Topic** | [TOPIC.md](TOPIC.md) |
| **Brief** | [SOFTWARE_PROJECT.tex](SOFTWARE_PROJECT.tex) |
| **Repository** | https://github.com/nadir2609/AI-Research-Assistant |
| **Final tag** | `v1.0-final` (before submission) |

---

## Quick start

### Option A — Docker (recommended)

Starts **PostgreSQL** (schema auto-created), verifies tables, runs the **API** on port **8000**. No local Postgres install required.

```powershell
# Windows
.\run.ps1
```

```bash
# macOS / Linux
chmod +x run.sh && ./run.sh

# or
docker compose up --build
```

Then open http://localhost:8000/health — expect `{"status":"ok"}`.

For live research via `/ask`, copy [.env.docker.example](.env.docker.example) to `.env` and add your API keys, then restart: `docker compose up --build`.

### Option B — Local Python

```bash
python -m venv .venv && .\.venv\Scripts\Activate.ps1   # Windows
pip install -r requirements-runtime.txt
pip install pytest pytest-asyncio pytest-cov respx
copy .env.example .env
# edit .env with API keys
python demo_ai.py --offline
python -m researcher ask "What is photosynthesis?" --sources wiki,arxiv
```

---

## Features

- **Parallel source fetch** — `asyncio.gather`, per-source timeouts, graceful degradation
- **Shared `httpx` client** — `follow_redirects=True` for arXiv (no `ai/` edits needed)
- **Retries & rate limits** — token buckets, exponential backoff (`ExternalCallPolicy`)
- **Two-tier cache** — filesystem JSON (`CACHE_DIR`) + PostgreSQL (`research_cache`)
- **Answer history** — final Q&A stored in `research_history` when DB is connected
- **Validation** — CLI and FastAPI entry points
- **Docker Compose** — Postgres + API in one command (`run.ps1` / `run.sh`)

---

## Architecture

```mermaid
flowchart TB
  subgraph entry [Entry points]
    CLI[CLI]
    API[FastAPI]
  end
  CLI --> R[Researcher]
  API --> R
  R --> S[ResearchService]
  S --> V[validation]
  S --> C[TieredSourceCache]
  C --> FS[(Filesystem cache)]
  C --> PG[(PostgreSQL cache)]
  S --> O[ResearchOrchestrator]
  O --> P[ExternalCallPolicy]
  P --> AI["ai.fetch_* / synthesize"]
  S --> H[research_history]
```

| Component | Path |
|-----------|------|
| Provided AI module | `ai/` — **do not edit** |
| Settings | `src/config.py` |
| Parallel fetch | `src/concurrency/orchestrator.py` |
| Pipeline | `src/services/research_service.py` |
| Retries / limits | `src/services/external_policy.py` |
| Storage | `src/storage/` |
| CLI / API | `src/cli.py`, `src/api.py` |

---

## Prerequisites

| Need | Local dev | Docker |
|------|-----------|--------|
| Python 3.12+ | Yes | Included in image |
| API keys | For live `/ask` or CLI | Optional in `.env` |
| PostgreSQL | Optional | Included via Compose |
| Docker Desktop | — | Yes |

---

## Configuration

Copy a template and add secrets (never commit `.env`):

```bash
copy .env.example .env          # local development
copy .env.docker.example .env   # Docker Compose (recommended)
```

### Required for live research

| Variable | Example | Notes |
|----------|---------|-------|
| `LLM_PROVIDER` | `anthropic` / `openai` / `gemini` | Must match your API key |
| `LLM_MODEL` | `claude-sonnet-4-6` | Provider-specific model |
| `ANTHROPIC_API_KEY` | `sk-...` | When `LLM_PROVIDER=anthropic` |
| `WEB_SEARCH_PROVIDER` | `tavily` / `serper` / `duckduckgo` | |
| `TAVILY_API_KEY` | `tvly-...` | When using Tavily |

### Optional / SE tuning

| Variable | Default | Purpose |
|----------|---------|---------|
| `DATABASE_URL` | — | PostgreSQL; unset = filesystem cache only |
| `CACHE_DIR` | `./.cache` | Filesystem cache root |
| `CACHE_TTL_SECONDS` | `86400` | Cache expiry |
| `PER_SOURCE_TIMEOUT_SECONDS` | `10` | Per-source fetch timeout |
| `REQUIRE_PROVIDER_KEYS` | `true` | Set `false` in Docker so API starts without keys |
| `LOG_LEVEL` | `INFO` | Logging verbosity |

Full list: [.env.example](.env.example) and [.env.docker.example](.env.docker.example).

**Docker Compose** sets `DATABASE_URL=postgresql://user:password@postgres:5432/research_assistant` and `REQUIRE_PROVIDER_KEYS=false` automatically (Compose `environment` overrides `.env` for those keys).

---

## Run locally

### Verify the provided `ai/` module (no keys, no network)

```bash
python demo_ai.py --offline
python demo_ai.py --offline --limit 3
pytest tests/test_ai_smoke.py -v
```

### CLI

```bash
python -m researcher ask "What is photosynthesis?" --sources wiki,arxiv,web
python -m researcher ask "What is photosynthesis?" --no-cache
```

Source aliases: `wiki` / `wikipedia`, `arxiv`, `web` (default: all three).

### HTTP API

```bash
uvicorn src.api:app --reload --host 127.0.0.1 --port 8000
```

```bash
curl http://127.0.0.1:8000/health

curl -s -X POST http://127.0.0.1:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question":"What is photosynthesis?","sources":["wiki","arxiv"],"no_cache":false}'
```

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/ask `
  -ContentType "application/json" `
  -Body '{"question":"What is photosynthesis?","sources":["wiki","arxiv"],"no_cache":false}'
```

Sample questions: [data/research_questions.json](data/research_questions.json).

---

## PostgreSQL

### With Docker (automatic)

Compose runs Postgres 16 and applies [docker/postgres/01-init.sql](docker/postgres/01-init.sql) on first start:

| Table | Purpose |
|-------|---------|
| `research_cache` | Cached source fetch results (`source_type`, `query_text`, `content` JSONB) |
| `research_history` | Final answers and citations |

Credentials (Compose defaults): **user** / **password**, database **research_assistant**, host **localhost:5432**.

Verify from the stack:

```bash
docker compose run --rm app python check_db.py
```

### Without Docker (manual)

```bash
psql -U postgres -f src/storage/Research_Assistant_db.sql
```

Set `DATABASE_URL` in `.env`, then:

```bash
python check_db.py
```

If the DB is down or `DATABASE_URL` is unset, the app continues with **filesystem cache only**.

---

## Docker

### What starts

| Service | Container | Port | Role |
|---------|-----------|------|------|
| `postgres` | `research-postgres` | 5432 | DB + auto schema |
| `app` | `research-app` | 8000 | FastAPI after DB ready |
| `demo` | (profile) | — | Offline demo, one-shot |

Startup flow:

```
postgres (healthy) → wait_for_db → verify_stack → uvicorn
```

Scripts: [docker/wait_for_db.py](docker/wait_for_db.py), [docker/verify_stack.py](docker/verify_stack.py), [docker/entrypoint.sh](docker/entrypoint.sh).

### Commands

```bash
# Start stack (build + run)
docker compose up --build

# Detached
docker compose up --build -d

# Stop
docker compose down

# Wipe DB volume (fresh schema)
docker compose down -v

# Offline demo (no API keys)
docker compose --profile demo run --rm demo

# CLI one-off
docker compose run --rm app python -m researcher ask "What is photosynthesis?" --sources wiki,arxiv

# DB connectivity test
docker compose run --rm app python check_db.py

# Rebuild after code changes
docker compose build app && docker compose up -d
```

### Standalone image (no Postgres)

```bash
docker build -t research-assistant .
docker run --rm research-assistant
```

Runs `demo_ai.py --offline` (default `CMD`). No database required.

Dependencies: [requirements-runtime.txt](requirements-runtime.txt) · Compose: [docker-compose.yml](docker-compose.yml) · Image: [Dockerfile](Dockerfile).

---

## Testing

All tests are **offline** (mocked HTTP / DB):

```bash
pytest -v
pytest --cov=src --cov-report=term-missing
pytest tests/test_ai_smoke.py -v
```

Target: **≥ 60%** coverage on `src/`.

Inside Docker (rebuild image first if tests were added to the image):

```bash
docker compose build app
docker compose run --rm app pytest tests/test_ai_smoke.py -q
```

---

## Performance: sequential vs parallel

The CLI prints a **Source fetch summary** after each answer.

1. Clear cache: `--no-cache` or delete `./.cache`.
2. **Parallel:** one run with `--sources wiki,arxiv,web` — wall time ≈ **max** of source times + synthesis.
3. **Sequential:** three runs with one source each; **sum** the elapsed times.

```bash
python -m researcher ask "What is photosynthesis?" --sources wiki,arxiv,web --no-cache
```

| Mode | Wall-clock (s) | Notes |
|------|----------------|-------|
| Parallel (3 sources) | _TBD_ | Single run, read summary |
| Sequential (sum of 3) | _TBD_ | Three single-source runs |

---

## Project layout

```
AI-Research-Assistant/
├── ai/                          # Provided — do not modify
├── src/
│   ├── config.py
│   ├── cli.py
│   ├── api.py
│   ├── core/researcher.py
│   ├── concurrency/orchestrator.py
│   ├── services/
│   │   ├── research_service.py
│   │   └── external_policy.py
│   └── storage/
│       ├── Research_Assistant_db.sql
│       ├── repository.py
│       └── source_cache.py
├── docker/
│   ├── entrypoint.sh
│   ├── wait_for_db.py
│   ├── verify_stack.py
│   └── postgres/01-init.sql
├── tests/
├── data/research_questions.json
├── demo_ai.py
├── researcher.py
├── check_db.py
├── docker-compose.yml
├── Dockerfile
├── run.ps1 / run.sh
├── requirements-runtime.txt
├── requirements.txt
├── .env.example
├── .env.docker.example
└── TOPIC.md
```

---

## Submission checklist

- [ ] `pytest` passes; `pytest tests/test_ai_smoke.py` passes
- [ ] `pytest --cov=src` ≥ 60%
- [ ] `docker compose up --build` — `/health` returns OK
- [ ] `docker run --rm $(docker build -q .)` offline demo works
- [ ] `report/report.pdf` and presentation slides
- [ ] Signed contribution statement
- [ ] Git tag `v1.0-final` pushed; repo URL in report

Grading: **Code 60% · Report 25% · Presentation 15%** — see `SOFTWARE_PROJECT.tex` §8.

### Rules

- **Do not** edit `ai/` (contract / automatic deduction).
- **Do not** commit `.env` or API keys.
- **Do** disclose AI-assistant use in the report.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| arXiv `301 Moved Permanently` | `http` → `https` redirect | `follow_redirects=True` in `orchestrator.py` (included) |
| `Cache save failed ... PostgresSourceCache` | JSONB param type | `repository.py` uses `json.dumps` for cache rows |
| `Port 5432 already in use` | Local Postgres vs Compose | Stop local Postgres or change host port in `docker-compose.yml` |
| Stale / missing DB tables | Old Docker volume | `docker compose down -v` then `up --build` |
| API won't start without keys | `REQUIRE_PROVIDER_KEYS=true` | Use Compose (sets `false`) or add keys to `.env` |
| `/health` OK but `/ask` fails | Missing API keys | Add LLM + web-search keys to `.env` |
| Gemini `503` | Provider outage | Retries; retry later or switch provider |
| `wikipedia: 0 source(s)` | No search match | Normal for some queries |
| Changes not in container | Stale image | `docker compose build app --no-cache` |
| `check_db` insert fails | Raw list vs JSON string | Use latest `check_db.py` (`json.dumps`); rebuild image |

---

## License & acknowledgements

Course materials © AI Academy, National AI Center. The `ai/` package is provided as-is. Document any AI coding assistants used in the project report.
